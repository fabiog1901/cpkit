"""Generic queue worker loop."""

import asyncio
import concurrent.futures
import logging
import random
from collections.abc import Callable, Mapping
from typing import Any, Literal

from psycopg import IntegrityError
from psycopg.pq import TransactionStatus
from psycopg.rows import class_row

from cpkit.audit import job_id_ctx

from .maintenance import FAIL_ZOMBIE_JOBS_MESSAGE_TYPE, create_fail_zombie_jobs_handler
from .recurring import get_recurring_messages, recurring_message_map
from .repository import QUEUE_TABLE
from .types import QueueMessage, RecurringMessage

logger = logging.getLogger(__name__)

QueueHandler = Callable[[int, Any, str], None]
ResolveHandler = Callable[[QueueMessage], QueueHandler | None]
ParseMessage = Callable[[QueueMessage], Any]
FailureHandler = Callable[[QueueMessage, Exception], None]


class QueueDispatchError(RuntimeError):
    """A selected message could not safely proceed to handler submission.

    The original database/executor exception is available as ``__cause__``.
    Unknown or committed outcomes require reconciliation before restarting.
    """

    def __init__(
        self,
        message: QueueMessage,
        phase: Literal[
            "commit_rejected", "commit_unknown", "committed_cleanup", "submission"
        ],
    ):
        self.message = message
        self.phase = phase
        super().__init__(
            f"Queue message {message.msg_id} ({message.msg_type}): {phase}; "
            "handler not submitted"
        )


def create_queue_worker(
    *,
    get_pool: Callable[[], Any],
    get_repo: Callable[[], Any],
    handlers: Mapping[Any, QueueHandler] | None = None,
    resolve_handler: ResolveHandler | None = None,
    parse_message: ParseMessage | None = None,
    handle_failure: FailureHandler | None = None,
    failed_status: str = "FAILED",
    recurring_messages: tuple[RecurringMessage, ...] | None = None,
) -> Callable[[], Any]:
    """Create a background task that polls the framework queue."""
    maintenance_handlers = {
        FAIL_ZOMBIE_JOBS_MESSAGE_TYPE: create_fail_zombie_jobs_handler(get_repo),
    }

    def record_failure(message: QueueMessage, err: Exception) -> None:
        if not message.is_recurring:
            try:
                get_repo().update_job(message.msg_id, failed_status)
            except Exception:
                logger.exception("Unable to mark job %s as failed", message.msg_id)
        if handle_failure is not None:
            handle_failure(message, err)

    async def pull_from_mq() -> None:
        await run_queue_worker(
            get_pool=get_pool,
            resolve_handler=_resolve_worker_handler(
                maintenance_handlers,
                handlers,
                resolve_handler,
            ),
            parse_message=_parse_worker_message(
                maintenance_handlers,
                parse_message,
            ),
            handle_failure=record_failure,
            recurring_messages=(
                recurring_messages
                if recurring_messages is not None
                else get_recurring_messages()
            ),
        )

    return pull_from_mq


def _resolve_worker_handler(
    maintenance_handlers: Mapping[str, QueueHandler],
    handlers: Mapping[Any, QueueHandler] | None,
    resolve_handler: ResolveHandler | None,
) -> ResolveHandler:
    def resolve(message: QueueMessage) -> QueueHandler | None:
        handler = maintenance_handlers.get(message.msg_type)
        if handler is not None:
            return handler
        if handlers is not None:
            handler = handlers.get(message.msg_type)
            if handler is not None:
                return handler
        if resolve_handler is None:
            return None
        return resolve_handler(message)

    return resolve


def _parse_worker_message(
    maintenance_handlers: Mapping[str, QueueHandler],
    parse_message: ParseMessage | None,
) -> ParseMessage:
    def parse(message: QueueMessage) -> Any:
        if message.msg_type in maintenance_handlers:
            return message.msg_data
        if parse_message is None:
            return message.msg_data
        return parse_message(message)

    return parse


async def run_queue_worker(
    *,
    get_pool: Callable[[], Any],
    handlers: Mapping[Any, QueueHandler] | None = None,
    resolve_handler: ResolveHandler | None = None,
    parse_message: ParseMessage | None = None,
    handle_failure: FailureHandler | None = None,
    recurring_messages: tuple[RecurringMessage, ...] = (),
    poll_seconds: float = 5,
    jitter_min: float = 0.7,
    jitter_max: float = 1.3,
) -> None:
    """Continuously claim due queue messages and dispatch them to handlers."""
    running_handlers: set[asyncio.Future] = set()
    recurring_configs = recurring_message_map(recurring_messages)
    try:
        while True:
            await asyncio.sleep(poll_seconds * random.uniform(jitter_min, jitter_max))
            try:
                loop = asyncio.get_running_loop()
                prepared = _claim_and_prepare_dispatch(
                    get_pool=get_pool,
                    recurring_configs=recurring_configs,
                    handlers=handlers,
                    resolve_handler=resolve_handler,
                    parse_message=parse_message,
                )
                if prepared is None:
                    continue
                message, handler, payload = prepared
                try:
                    future = loop.run_in_executor(
                        None,
                        _run_queue_handler,
                        message,
                        handler,
                        payload,
                        handle_failure,
                    )
                except Exception as err:
                    raise QueueDispatchError(message, "submission") from err
                running_handlers.add(future)
                future.add_done_callback(running_handlers.discard)
                future.add_done_callback(_log_handler_crash)
            except QueueDispatchError as err:
                logger.exception("Queue dispatch failed: %s", err)
                if err.phase != "commit_rejected":
                    raise
            except Exception:
                logger.exception("Unexpected failure while polling the message queue")

    except asyncio.CancelledError:
        logger.info("Queue worker was stopped")
        for future in running_handlers:
            future.cancel()
        raise


def _claim_and_prepare_dispatch(
    *,
    get_pool: Callable[[], Any],
    recurring_configs: Mapping[str, RecurringMessage],
    handlers: Mapping[Any, QueueHandler] | None,
    resolve_handler: ResolveHandler | None,
    parse_message: ParseMessage | None,
) -> tuple[QueueMessage, QueueHandler, Any] | None:
    """Resolve/parse and commit disposition without executing application work."""
    message = None
    committing = False
    committed = False
    try:
        with get_pool().connection() as conn:
            # A nested transaction would only release a savepoint, not commit
            # the claim. Require a fresh connection transaction for dispatch.
            if conn.info.transaction_status != TransactionStatus.IDLE:
                raise ValueError("Queue dispatch requires an idle connection")
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=class_row(QueueMessage)) as cur:
                        message = _claim_due_recurring_message(cur, recurring_configs)
                        if message is None:
                            message = _claim_due_message(cur)
                        if message is None:
                            return None
                        logger.info(
                            "Preparing queue message %s of type %s",
                            message.msg_id,
                            message.msg_type,
                        )
                        handler = _resolve_handler(
                            message,
                            handlers=handlers,
                            resolve_handler=resolve_handler,
                        )
                        payload = (
                            parse_message(message)
                            if parse_message is not None
                            else message.msg_data
                        )
                        if not message.is_recurring:
                            cur.execute(
                                f"DELETE FROM {QUEUE_TABLE} WHERE msg_id = %s;",
                                (message.msg_id,),
                            )
                    committing = True
                committed = True
            except Exception as err:
                if committing:
                    phase = (
                        "commit_rejected"
                        if (
                            isinstance(err, IntegrityError)
                            or getattr(err, "sqlstate", None)
                            in {"40000", "40001", "40002", "40P01"}
                        )
                        else "commit_unknown"
                    )
                    raise QueueDispatchError(message, phase) from err
                raise
    except QueueDispatchError:
        raise
    except Exception as err:
        if committed:
            raise QueueDispatchError(message, "committed_cleanup") from err
        if committing:
            # Pool cleanup can replace the original commit exception. Never
            # turn an uncertain commit into an ordinary polling retry.
            raise QueueDispatchError(message, "commit_unknown") from err
        raise
    return message, handler, payload


def _claim_due_message(cur) -> QueueMessage | None:
    return cur.execute(f"""
        SELECT *
        FROM {QUEUE_TABLE}
        WHERE is_recurring = false
            AND now() > start_after
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """).fetchone()


def _claim_due_recurring_message(
    cur,
    recurring_configs: Mapping[str, RecurringMessage],
) -> QueueMessage | None:
    if not recurring_configs:
        return None

    message = cur.execute(
        f"""
        SELECT *
        FROM {QUEUE_TABLE}
        WHERE is_recurring = true
            AND msg_type = ANY(%s)
            AND now() > start_after
        ORDER BY start_after
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """,
        (list(recurring_configs),),
    ).fetchone()
    if message is None:
        return None

    recurring_config = recurring_configs[message.msg_type]
    previous_start_after = message.start_after
    rescheduled = cur.execute(
        f"""
        UPDATE {QUEUE_TABLE}
        SET start_after = now()
            + (%s * INTERVAL '1s')
            + (random() * (%s * INTERVAL '1s'))
        WHERE msg_id = %s
        RETURNING *
        """,
        (
            recurring_config.interval_seconds,
            recurring_config.jitter_seconds,
            message.msg_id,
        ),
    ).fetchone()
    logger.info(
        "Claimed and rescheduled recurring queue message %s of type %s "
        "from %s to %s using interval=%ss jitter=%ss",
        rescheduled.msg_id,
        rescheduled.msg_type,
        previous_start_after,
        rescheduled.start_after,
        recurring_config.interval_seconds,
        recurring_config.jitter_seconds,
    )
    return rescheduled


def _set_current_job_id(message: QueueMessage):
    if message.is_recurring or message.msg_type == FAIL_ZOMBIE_JOBS_MESSAGE_TYPE:
        return None
    return job_id_ctx.set(message.msg_id)


def _run_queue_handler(
    message: QueueMessage,
    handler: QueueHandler,
    payload: Any,
    handle_failure: FailureHandler | None,
) -> None:
    job_id_token = _set_current_job_id(message)
    try:
        handler(message.msg_id, payload, message.created_by)
    except Exception as err:
        logger.exception(
            "Queue message %s failed during dispatch",
            message.msg_id,
        )
        if handle_failure is not None:
            try:
                handle_failure(message, err)
            except Exception:
                logger.exception(
                    "Queue message %s failure hook failed",
                    message.msg_id,
                )
    finally:
        if job_id_token is not None:
            job_id_ctx.reset(job_id_token)


def _log_handler_crash(future: asyncio.Future) -> None:
    try:
        future.result()
    except asyncio.CancelledError:
        pass
    except concurrent.futures.CancelledError:
        pass
    except Exception:
        logger.exception("Queue handler crashed unexpectedly")


def _resolve_handler(
    message: QueueMessage,
    *,
    handlers: Mapping[Any, QueueHandler] | None,
    resolve_handler: ResolveHandler | None,
) -> QueueHandler:
    if resolve_handler is not None:
        handler = resolve_handler(message)
    elif handlers is not None:
        handler = handlers.get(message.msg_type)
    else:
        handler = None

    if handler is None:
        raise ValueError(f"Unknown task type requested: {message.msg_type}")
    return handler
