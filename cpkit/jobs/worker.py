"""Generic queue worker loop."""

import asyncio
import concurrent.futures
import logging
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class HandlerOutcome:
    """Handler and failure-hook results after both have returned."""

    error: Exception | None = None
    failure_hook_error: Exception | None = None


@dataclass(frozen=True, eq=False)
class HandlerCompletion:
    """Non-cancelling access to one actual executor invocation."""

    message: QueueMessage
    payload: Any
    _future: concurrent.futures.Future[HandlerOutcome] = field(repr=False)

    @property
    def done(self) -> bool:
        return self._future.done()

    def result(self) -> HandlerOutcome:
        """Return the outcome, or raise TimeoutError if still running."""
        return self._future.result(timeout=0)

    async def wait(self, timeout: float | None = None) -> HandlerOutcome:
        """Wait without allowing timeout/cancellation to cancel the handler."""
        if self.done:
            return self.result()
        waiter = asyncio.wrap_future(self._future)
        # A cancelled caller may never retrieve an unexpected executor exception.
        waiter.add_done_callback(_observe_waiter)
        return await asyncio.wait_for(asyncio.shield(waiter), timeout)


def _observe_waiter(waiter: asyncio.Future) -> None:
    if not waiter.cancelled():
        waiter.exception()


@dataclass(frozen=True)
class DrainResult:
    """Unresolved invocations retain their original message and payload."""

    polling_stopped: bool
    unresolved: tuple[HandlerCompletion, ...]

    @property
    def complete(self) -> bool:
        return self.polling_stopped and not self.unresolved


class QueueWorker:
    """Single-use poller with an owned executor and explicit handler lifetime.

    Control methods belong to one asyncio event loop. Stopping is terminal.
    A complete drain joins only this worker's executor, never the loop's default.
    """

    def __init__(
        self,
        *,
        get_pool: Callable[[], Any],
        handlers: Mapping[Any, QueueHandler] | None = None,
        resolve_handler: ResolveHandler | None = None,
        parse_message: ParseMessage | None = None,
        handle_failure: FailureHandler | None = None,
        recurring_messages: (
            tuple[RecurringMessage, ...] | Callable[[], tuple[RecurringMessage, ...]]
        ) = (),
        poll_seconds: float = 5,
        jitter_min: float = 0.7,
        jitter_max: float = 1.3,
    ):
        self._get_pool = get_pool
        self._handlers = handlers
        self._resolve_handler = resolve_handler
        self._parse_message = parse_message
        self._handle_failure = handle_failure
        self._recurring_messages = recurring_messages
        self._poll_seconds = poll_seconds
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max
        self._stop = asyncio.Event()
        self._polling_stopped = asyncio.Event()
        self._polling_stopped.set()
        self._started = False
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._pending: set[HandlerCompletion] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("QueueWorker controls must use the same event loop")
        self._loop = loop

    @property
    def active_handlers(self) -> tuple[HandlerCompletion, ...]:
        """Snapshot handles for queued/running handler invocations."""
        return tuple(handle for handle in self._pending if not handle.done)

    def stop_polling(self) -> None:
        """Prevent further claims; leave submitted invocations untouched."""
        self._bind_loop()
        self._stop.set()

    async def _wait_for_poll(self) -> bool:
        delay = self._poll_seconds * random.uniform(self._jitter_min, self._jitter_max)
        if self._stop.is_set():
            return True
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
            return True
        except TimeoutError:
            return self._stop.is_set()

    async def __call__(self) -> None:
        await self.run()

    def _begin(self) -> None:
        self._bind_loop()
        if self._started:
            raise RuntimeError("QueueWorker can only be run once")
        self._started = True
        self._polling_stopped.clear()

    def _finish(self) -> None:
        self._stop.set()
        self._polling_stopped.set()

    def _recurring_configs(self) -> Mapping[str, RecurringMessage]:
        messages = (
            self._recurring_messages()
            if callable(self._recurring_messages)
            else self._recurring_messages
        )
        return recurring_message_map(messages)

    def _dispatch(
        self,
        configs: Mapping[str, RecurringMessage],
        *,
        message_id: int | None = None,
        expected_type: str | None = None,
        expected_actor: str | None = None,
    ) -> HandlerCompletion | None:
        prepared = _claim_and_prepare_dispatch(
            get_pool=self._get_pool,
            recurring_configs=configs,
            handlers=self._handlers,
            resolve_handler=self._resolve_handler,
            parse_message=self._parse_message,
            message_id=message_id,
            expected_type=expected_type,
            expected_actor=expected_actor,
        )
        if prepared is None:
            return None
        message, handler, payload = prepared
        try:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    thread_name_prefix="cpkit-queue"
                )
            future = self._executor.submit(
                _run_queue_handler,
                message,
                handler,
                payload,
                self._handle_failure,
            )
        except Exception as err:
            raise QueueDispatchError(message, "submission") from err
        handle = HandlerCompletion(message, payload, future)
        self._pending.add(handle)
        future.add_done_callback(_log_handler_crash)
        # A retained handle remains usable after it leaves the active set.
        self._pending = set(self.active_handlers)
        return handle

    async def dispatch_one(
        self,
        *,
        message_id: int,
        include_recurring: bool = False,
        expected_type: str | None = None,
        expected_actor: str | None = None,
    ) -> HandlerCompletion | None:
        """Attempt one due ID, using the registered parser/handler and lifecycle.

        No polling/retry or follow-up selection occurs. Return None for absent,
        not-due, locked, excluded, or mismatched work. Parsing/resolution/commit
        errors propagate. Parsing/resolution failures roll back; commit and
        submission errors retain QueueDispatchError phases. The owner must drain.
        """
        if isinstance(message_id, bool) or not isinstance(message_id, int):
            raise TypeError("message_id must be an integer")
        self._begin()
        try:
            if self._stop.is_set():
                return None
            return self._dispatch(
                self._recurring_configs() if include_recurring else {},
                message_id=message_id,
                expected_type=expected_type,
                expected_actor=expected_actor,
            )
        finally:
            self._finish()

    async def run(self) -> None:
        """Poll until stopped/cancelled; the owner must subsequently drain."""
        self._begin()
        try:
            if self._stop.is_set():
                return
            configs = self._recurring_configs()
            while not await self._wait_for_poll():
                try:
                    self._dispatch(configs)
                except QueueDispatchError as err:
                    logger.exception("Queue dispatch failed: %s", err)
                    if err.phase != "commit_rejected":
                        raise
                except Exception:
                    logger.exception(
                        "Unexpected failure while polling the message queue"
                    )
        finally:
            self._finish()

    async def drain(self, timeout: float | None = None) -> DrainResult:
        """Stop polling and join actual work, or return unresolved handles.

        Timeout/cancellation never cancels executor work. A later call can
        complete the drain. Synchronous claim code can delay event-loop timers.
        """
        self.stop_polling()
        try:
            async with asyncio.timeout(timeout):
                await self._polling_stopped.wait()
                handles = self.active_handlers
                if handles:
                    # wait() insulates the concurrent futures from cancellation.
                    await asyncio.gather(
                        *(handle.wait() for handle in handles), return_exceptions=True
                    )
        except TimeoutError:
            pass
        unresolved = self.active_handlers
        self._pending = set(unresolved)
        stopped = self._polling_stopped.is_set()
        if stopped and not unresolved and self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        return DrainResult(stopped, unresolved)


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
) -> QueueWorker:
    """Create a callable, owned queue worker with stop/drain controls."""
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

    return QueueWorker(
        get_pool=get_pool,
        resolve_handler=_resolve_worker_handler(
            maintenance_handlers,
            handlers,
            resolve_handler,
        ),
        parse_message=_parse_worker_message(maintenance_handlers, parse_message),
        handle_failure=record_failure,
        recurring_messages=(
            recurring_messages
            if recurring_messages is not None
            else get_recurring_messages
        ),
    )


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
    """Run a standalone worker and fully drain its owned executor on exit.

    Cancellation waits for real handler completion. Use QueueWorker directly
    for a separately observable poller and bounded drain.
    """
    worker = QueueWorker(
        get_pool=get_pool,
        handlers=handlers,
        resolve_handler=resolve_handler,
        parse_message=parse_message,
        handle_failure=handle_failure,
        recurring_messages=recurring_messages,
        poll_seconds=poll_seconds,
        jitter_min=jitter_min,
        jitter_max=jitter_max,
    )
    try:
        await worker.run()
    finally:
        cancelled = False
        while True:
            try:
                await worker.drain()
                break
            except asyncio.CancelledError:
                # This convenience API has no external lifecycle owner. Even a
                # repeated cancellation must not abandon its executor/handlers.
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError


def _claim_and_prepare_dispatch(
    *,
    get_pool: Callable[[], Any],
    recurring_configs: Mapping[str, RecurringMessage],
    handlers: Mapping[Any, QueueHandler] | None,
    resolve_handler: ResolveHandler | None,
    parse_message: ParseMessage | None,
    message_id: int | None = None,
    expected_type: str | None = None,
    expected_actor: str | None = None,
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
                        selection = dict(
                            message_id=message_id,
                            expected_type=expected_type,
                            expected_actor=expected_actor,
                        )
                        message = _claim_due_recurring_message(
                            cur,
                            recurring_configs,
                            **selection,
                        )
                        if message is None:
                            message = _claim_due_message(cur, **selection)
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


def _selection_conditions(
    message_id: int | None,
    expected_type: str | None,
    expected_actor: str | None,
) -> tuple[str, tuple]:
    conditions = []
    values = []
    for column, value in (
        ("msg_id", message_id),
        ("msg_type", expected_type),
        ("created_by", expected_actor),
    ):
        if value is not None:
            conditions.append(f" AND {column} = %s")
            values.append(value)
    return "".join(conditions), tuple(values)


def _claim_due_message(
    cur,
    *,
    message_id: int | None = None,
    expected_type: str | None = None,
    expected_actor: str | None = None,
) -> QueueMessage | None:
    conditions, values = _selection_conditions(
        message_id, expected_type, expected_actor
    )
    return cur.execute(
        f"""
        SELECT *
        FROM {QUEUE_TABLE}
        WHERE is_recurring = false
            AND now() > start_after
            {conditions}
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """,
        values,
    ).fetchone()


def _claim_due_recurring_message(
    cur,
    recurring_configs: Mapping[str, RecurringMessage],
    *,
    message_id: int | None = None,
    expected_type: str | None = None,
    expected_actor: str | None = None,
) -> QueueMessage | None:
    if not recurring_configs:
        return None

    conditions, values = _selection_conditions(
        message_id, expected_type, expected_actor
    )
    message = cur.execute(
        f"""
        SELECT *
        FROM {QUEUE_TABLE}
        WHERE is_recurring = true
            AND msg_type = ANY(%s)
            AND now() > start_after
            {conditions}
        ORDER BY start_after
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """,
        (list(recurring_configs), *values),
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
) -> HandlerOutcome:
    job_id_token = _set_current_job_id(message)
    error = None
    failure_hook_error = None
    try:
        handler(message.msg_id, payload, message.created_by)
    except Exception as err:
        error = err
        logger.exception(
            "Queue message %s failed during dispatch",
            message.msg_id,
        )
        if handle_failure is not None:
            try:
                handle_failure(message, err)
            except Exception as hook_err:
                failure_hook_error = hook_err
                logger.exception(
                    "Queue message %s failure hook failed",
                    message.msg_id,
                )
    finally:
        if job_id_token is not None:
            job_id_ctx.reset(job_id_token)
    return HandlerOutcome(error, failure_hook_error)


def _log_handler_crash(future: concurrent.futures.Future) -> None:
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
