import asyncio
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from psycopg import OperationalError
from psycopg.errors import (
    CheckViolation,
    SerializationFailure,
    StatementCompletionUnknown,
)
from psycopg.pq import TransactionStatus
from test_jobs_worker import FakeCursor, FakePool

from cpkit.jobs.types import QueueMessage, RecurringMessage
from cpkit.jobs.worker import QueueDispatchError, run_queue_worker


def message(recurring=False):
    return QueueMessage(
        msg_id=1,
        msg_type="TEST",
        msg_data={"x": 1},
        start_after=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        created_by="actor",
        is_recurring=recurring,
    )


class TransactionPool(FakePool):
    def __init__(self, *, recurring=False, commit_error=None, cleanup_error=None):
        self.message = message(recurring)
        super().__init__(
            [] if recurring else [self.message], [self.message] if recurring else []
        )
        self.commit_error = commit_error
        self.cleanup_error = cleanup_error
        self.events = []
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)

    @contextmanager
    def connection(self):
        yield self
        self.events.append("connection_exit")
        if self.cleanup_error:
            raise self.cleanup_error

    @contextmanager
    def transaction(self):
        snapshot = (
            self.messages[:],
            self.recurring_messages[:],
            self.deleted[:],
            self.updated[:],
        )
        try:
            yield
            self.events.append("commit")
            if self.commit_error:
                raise self.commit_error
        except BaseException:
            self.messages, self.recurring_messages, self.deleted, self.updated = (
                snapshot
            )
            self.events.append("rollback")
            raise

    def cursor(self, **kwargs):
        return FakeCursor(self)


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def poll_once(self, pool, **kwargs):
        ticks = 0

        async def tick(_seconds):
            nonlocal ticks
            ticks += 1
            if ticks > 1:
                raise asyncio.CancelledError

        executor = Mock(return_value=asyncio.get_running_loop().create_future())
        executor.side_effect = kwargs.pop("submit", None)
        with (
            patch("cpkit.jobs.worker.asyncio.sleep", tick),
            patch.object(asyncio.get_running_loop(), "run_in_executor", executor),
            patch("cpkit.jobs.worker.logger.exception"),
        ):
            try:
                await run_queue_worker(
                    get_pool=lambda: pool,
                    handlers={"TEST": Mock()},
                    recurring_messages=(RecurringMessage("TEST", 300),),
                    **kwargs,
                )
            except asyncio.CancelledError:
                pass
        return executor

    async def test_submission_follows_commit_and_connection_release(self):
        for recurring in (False, True):
            pool = TransactionPool(recurring=recurring)

            def submit(*args):
                self.assertEqual(pool.events, ["commit", "connection_exit"])
                self.assertEqual(pool.deleted, [] if recurring else [1])
                return asyncio.get_running_loop().create_future()

            executor = await self.poll_once(pool, submit=submit)
            executor.assert_called_once()
            self.assertEqual(executor.call_args.args[4], {"x": 1})

    async def test_parser_and_resolver_refusal_preserve_queue(self):
        for recurring in (False, True):
            for kwargs in (
                {"parse_message": Mock(side_effect=ValueError("invalid"))},
                {"resolve_handler": lambda message: None},
            ):
                pool = TransactionPool(recurring=recurring)
                executor = await self.poll_once(pool, **kwargs)
                executor.assert_not_called()
                self.assertEqual(pool.deleted, [])
                self.assertEqual(pool.updated, [])
                self.assertEqual(
                    pool.messages + pool.recurring_messages, [pool.message]
                )
                self.assertEqual(pool.events, ["rollback"])

    async def test_confirmed_commit_rejection_does_not_submit(self):
        for error in (SerializationFailure("conflict"), CheckViolation("constraint")):
            pool = TransactionPool(commit_error=error)
            executor = await self.poll_once(pool)
            executor.assert_not_called()
            self.assertEqual(pool.messages, [pool.message])

    async def test_disposition_statement_failure_rolls_back_without_submission(self):
        pool = TransactionPool()
        original_execute = FakeCursor.execute

        def fail_delete(cursor, stmt, bind_args=()):
            if "DELETE" in stmt:
                raise RuntimeError("delete failed")
            return original_execute(cursor, stmt, bind_args)

        with patch.object(FakeCursor, "execute", fail_delete):
            executor = await self.poll_once(pool)
        executor.assert_not_called()
        self.assertEqual(pool.messages, [pool.message])
        self.assertEqual(pool.events, ["rollback"])

    async def test_uncertain_commit_stops_worker_with_context(self):
        pool = TransactionPool(commit_error=OperationalError("connection lost"))
        with self.assertRaises(QueueDispatchError) as caught:
            await self.poll_once(pool)
        self.assertEqual(caught.exception.phase, "commit_unknown")
        self.assertEqual(caught.exception.message, pool.message)
        self.assertIs(caught.exception.__cause__, pool.commit_error)

    async def test_statement_completion_unknown_is_not_a_confirmed_rollback(self):
        pool = TransactionPool(commit_error=StatementCompletionUnknown("uncertain"))
        with self.assertRaises(QueueDispatchError) as caught:
            await self.poll_once(pool)
        self.assertEqual(caught.exception.phase, "commit_unknown")

    async def test_submission_failure_stops_without_requeue_or_failure_hook(self):
        pool = TransactionPool()
        failure_hook = Mock()
        with self.assertRaises(QueueDispatchError) as caught:
            await self.poll_once(
                pool,
                submit=RuntimeError("executor closed"),
                handle_failure=failure_hook,
            )
        self.assertEqual(caught.exception.phase, "submission")
        self.assertEqual(pool.messages, [])
        self.assertEqual(pool.deleted, [1])
        failure_hook.assert_not_called()

    async def test_connection_cleanup_after_commit_stops_without_submission(self):
        pool = TransactionPool(cleanup_error=RuntimeError("pool cleanup"))
        with self.assertRaises(QueueDispatchError) as caught:
            await self.poll_once(pool)
        self.assertEqual(caught.exception.phase, "committed_cleanup")
        self.assertEqual(pool.deleted, [1])

    async def test_cleanup_error_cannot_hide_uncertain_commit(self):
        class BrokenCleanupPool(TransactionPool):
            @contextmanager
            def connection(self):
                try:
                    yield self
                finally:
                    raise RuntimeError("cleanup replaced commit error")

        pool = BrokenCleanupPool(commit_error=OperationalError("connection lost"))
        with self.assertRaises(QueueDispatchError) as caught:
            await self.poll_once(pool)
        self.assertEqual(caught.exception.phase, "commit_unknown")

    async def test_outer_transaction_is_refused(self):
        pool = TransactionPool()
        pool.info.transaction_status = TransactionStatus.INTRANS
        executor = await self.poll_once(pool)
        executor.assert_not_called()
        self.assertEqual(pool.messages, [pool.message])
