import asyncio
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cpkit.jobs.types import QueueMessage, RecurringMessage
from cpkit.jobs.worker import (
    _claim_due_recurring_message,
    _run_queue_handler,
    run_queue_worker,
)


class FakePool:
    def __init__(self, messages, recurring_messages=()):
        self.messages = list(messages)
        self.recurring_messages = list(recurring_messages)
        self.deleted = []
        self.updated = []
        self.lock = threading.Lock()

    def connection(self):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def cursor(self, row_factory=None):
        return FakeCursor(self.pool)

    def transaction(self):
        return self


class FakeCursor:
    def __init__(self, pool):
        self.pool = pool
        self.selected = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, stmt, bind_args=()):
        if "SELECT" in stmt and "is_recurring = true" in stmt:
            with self.pool.lock:
                self.selected = (
                    self.pool.recurring_messages.pop(0)
                    if self.pool.recurring_messages
                    else None
                )
            return self
        if "UPDATE" in stmt and "RETURNING *" in stmt:
            self.pool.updated.append(bind_args)
            if self.selected is not None:
                self.selected = self.selected.model_copy(
                    update={
                        "start_after": datetime.now(timezone.utc)
                        + timedelta(seconds=300),
                        "is_recurring": True,
                    }
                )
            return self
        if "SELECT" in stmt:
            with self.pool.lock:
                self.selected = (
                    self.pool.messages.pop(0) if self.pool.messages else None
                )
            return self
        if "DELETE" in stmt:
            self.pool.deleted.append(bind_args[0])
            return self
        raise AssertionError(f"Unexpected statement: {stmt}")

    def fetchone(self):
        return self.selected


class QueueWorkerTests(unittest.IsolatedAsyncioTestCase):
    def test_handler_failure_calls_failure_hook(self):
        message = QueueMessage(
            msg_id=1,
            start_after=datetime.now(timezone.utc),
            msg_type="TEST",
            msg_data={},
            created_at=datetime.now(timezone.utc),
            created_by="tester",
        )
        failures = []

        def handler(_job_id, _payload, _created_by):
            raise RuntimeError("boom")

        def handle_failure(failed_message, err):
            failures.append((failed_message.msg_id, str(err)))

        with patch("cpkit.jobs.worker.logger.exception"):
            _run_queue_handler(message, handler, {}, handle_failure)

        self.assertEqual(failures, [(1, "boom")])

    def test_claim_due_recurring_message_reschedules_in_place(self):
        message = QueueMessage(
            msg_id=7,
            start_after=datetime.now(timezone.utc),
            msg_type="HEALTH_CHECK",
            msg_data={"scope": "all"},
            created_at=datetime.now(timezone.utc),
            created_by="system",
            is_recurring=True,
        )
        pool = FakePool([], recurring_messages=[message])
        cursor = FakeCursor(pool)

        claimed = _claim_due_recurring_message(
            cursor,
            {
                "HEALTH_CHECK": RecurringMessage(
                    msg_type="HEALTH_CHECK",
                    interval_seconds=300,
                    jitter_seconds=10,
                )
            },
        )

        self.assertEqual(claimed.msg_id, 7)
        self.assertTrue(claimed.is_recurring)
        self.assertEqual(pool.updated, [(300, 10, 7)])

    async def test_worker_does_not_wait_for_handler_before_polling_next_message(self):
        loop = asyncio.get_running_loop()
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release_first = threading.Event()
        messages = [
            QueueMessage(
                msg_id=1,
                start_after=datetime.now(timezone.utc),
                msg_type="TEST",
                msg_data={},
                created_at=datetime.now(timezone.utc),
                created_by="tester",
            ),
            QueueMessage(
                msg_id=2,
                start_after=datetime.now(timezone.utc),
                msg_type="TEST",
                msg_data={},
                created_at=datetime.now(timezone.utc),
                created_by="tester",
            ),
        ]
        pool = FakePool(messages)

        def handler(job_id, _payload, _created_by):
            if job_id == 1:
                loop.call_soon_threadsafe(first_started.set)
                release_first.wait(timeout=5)
                return
            loop.call_soon_threadsafe(second_started.set)
            release_first.set()

        worker = asyncio.create_task(
            run_queue_worker(
                get_pool=lambda: pool,
                handlers={"TEST": handler},
                poll_seconds=0.01,
                jitter_min=1,
                jitter_max=1,
            )
        )
        try:
            await asyncio.wait_for(first_started.wait(), timeout=1)
            await asyncio.wait_for(second_started.wait(), timeout=1)
        finally:
            release_first.set()
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertEqual(pool.deleted, [1, 2])

    async def test_worker_reschedules_recurring_message_without_deleting_it(self):
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        message = QueueMessage(
            msg_id=7,
            start_after=datetime.now(timezone.utc),
            msg_type="HEALTH_CHECK",
            msg_data={},
            created_at=datetime.now(timezone.utc),
            created_by="system",
            is_recurring=True,
        )
        pool = FakePool([], recurring_messages=[message])

        def handler(_job_id, _payload, _created_by):
            loop.call_soon_threadsafe(started.set)

        worker = asyncio.create_task(
            run_queue_worker(
                get_pool=lambda: pool,
                handlers={"HEALTH_CHECK": handler},
                recurring_messages=(
                    RecurringMessage(
                        msg_type="HEALTH_CHECK",
                        interval_seconds=300,
                        jitter_seconds=10,
                    ),
                ),
                poll_seconds=0.01,
                jitter_min=1,
                jitter_max=1,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertEqual(pool.updated, [(300, 10, 7)])
        self.assertEqual(pool.deleted, [])

    async def test_recurring_handler_failure_does_not_delete_recurring_row(self):
        failed = asyncio.Event()
        loop = asyncio.get_running_loop()
        message = QueueMessage(
            msg_id=7,
            start_after=datetime.now(timezone.utc),
            msg_type="HEALTH_CHECK",
            msg_data={},
            created_at=datetime.now(timezone.utc),
            created_by="system",
            is_recurring=True,
        )
        pool = FakePool([], recurring_messages=[message])
        failures = []

        def handler(_job_id, _payload, _created_by):
            raise RuntimeError("boom")

        def handle_failure(failed_message, err):
            failures.append((failed_message.msg_id, str(err)))
            loop.call_soon_threadsafe(failed.set)

        worker = asyncio.create_task(
            run_queue_worker(
                get_pool=lambda: pool,
                handlers={"HEALTH_CHECK": handler},
                handle_failure=handle_failure,
                recurring_messages=(
                    RecurringMessage(
                        msg_type="HEALTH_CHECK",
                        interval_seconds=300,
                        jitter_seconds=10,
                    ),
                ),
                poll_seconds=0.01,
                jitter_min=1,
                jitter_max=1,
            )
        )
        try:
            with patch("cpkit.jobs.worker.logger.exception"):
                await asyncio.wait_for(failed.wait(), timeout=1)
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertEqual(failures, [(7, "boom")])
        self.assertEqual(pool.updated, [(300, 10, 7)])
        self.assertEqual(pool.deleted, [])


if __name__ == "__main__":
    unittest.main()
