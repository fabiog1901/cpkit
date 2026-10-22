import asyncio
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from test_jobs_worker import FakePool

from cpkit.jobs import (
    QueueDispatchError,
    QueueMessage,
    QueueWorker,
    create_queue_worker,
    run_queue_worker,
)


def queued_message(job_id=1):
    return QueueMessage(
        msg_id=job_id,
        msg_type="TEST",
        msg_data={"value": job_id},
        start_after=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        created_by="actual-actor",
    )


class QueueLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workers = []
        self.releases = []
        self.threads = []

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        for worker, task in self.workers:
            worker.stop_polling()
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError, QueueDispatchError:
                pass
            self.assertTrue((await worker.drain(timeout=3)).complete)
        for thread in self.threads:
            self.assertFalse(thread.is_alive(), "worker-owned thread was not joined")

    def blocked_handler(self):
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        self.releases.append(release)
        calls = []

        def handler(job_id, payload, actor):
            self.threads.append(threading.current_thread())
            calls.append((job_id, payload, actor))
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise RuntimeError("test handler was not released")

        return handler, started, release, calls

    def start_worker(self, handler, *, messages=None, **kwargs):
        pool = FakePool([queued_message()] if messages is None else messages)
        worker = QueueWorker(
            get_pool=lambda: pool,
            handlers={"TEST": handler},
            poll_seconds=0.001,
            **kwargs,
        )
        task = asyncio.create_task(worker.run())
        self.workers.append((worker, task))
        return worker, task, pool

    async def test_poll_cancellation_retains_actual_handle_until_later_join(self):
        handler, started, release, calls = self.blocked_handler()
        worker, task, pool = self.start_worker(handler)
        await asyncio.wait_for(started.wait(), 1)
        (handle,) = worker.active_handlers
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(handle.done)
        with self.assertRaises(TimeoutError):
            handle.result()
        result = await worker.drain(timeout=0.01)
        self.assertFalse(result.complete)
        self.assertTrue(result.polling_stopped)
        self.assertEqual(result.unresolved, (handle,))
        self.assertIs(worker.active_handlers[0], handle)
        self.assertEqual(handle.message.created_by, "actual-actor")
        self.assertEqual(handle.payload, {"value": 1})
        self.assertTrue(self.threads[0].is_alive())
        release.set()
        outcome = await handle.wait(timeout=1)
        self.assertIsNone(outcome.error)
        self.assertTrue((await worker.drain(timeout=1)).complete)
        self.assertEqual(worker.active_handlers, ())
        self.assertEqual(calls, [(1, {"value": 1}, "actual-actor")])
        self.assertEqual(pool.deleted, [1])

    async def test_cancelled_waiter_and_timed_out_waiter_do_not_cancel_handler(self):
        handler, started, release, calls = self.blocked_handler()
        worker, task, pool = self.start_worker(handler)
        await asyncio.wait_for(started.wait(), 1)
        (handle,) = worker.active_handlers
        worker.stop_polling()
        await task
        waiter = asyncio.create_task(handle.wait())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        with self.assertRaises(TimeoutError):
            await handle.wait(timeout=0.01)
        self.assertFalse(handle.done)
        self.assertIs(worker.active_handlers[0], handle)
        release.set()
        await handle.wait(timeout=1)
        self.assertTrue((await worker.drain()).complete)
        self.assertIsNone((await handle.wait(timeout=0)).error)
        self.assertEqual(len(calls), 1)

    async def test_cancelled_drain_retains_context_and_can_be_retried(self):
        handler, started, release, calls = self.blocked_handler()
        worker, task, pool = self.start_worker(handler)
        await asyncio.wait_for(started.wait(), 1)
        (handle,) = worker.active_handlers
        draining = asyncio.create_task(worker.drain())
        await task
        draining.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await draining
        self.assertEqual(worker.active_handlers, (handle,))
        self.assertFalse(handle.done)
        release.set()
        self.assertTrue((await worker.drain(timeout=1)).complete)
        self.assertEqual(len(calls), 1)

    async def test_failure_hook_is_part_of_actual_completion_and_reports_errors(self):
        hook_started = asyncio.Event()
        release_hook = threading.Event()
        self.releases.append(release_hook)
        loop = asyncio.get_running_loop()
        handler_error = ValueError("handler failed")
        hook_error = RuntimeError("hook failed")

        def handler(*args):
            raise handler_error

        def hook(message, err):
            self.threads.append(threading.current_thread())
            self.assertIs(err, handler_error)
            loop.call_soon_threadsafe(hook_started.set)
            release_hook.wait(timeout=5)
            raise hook_error

        with patch("cpkit.jobs.worker.logger.exception"):
            worker, task, pool = self.start_worker(handler, handle_failure=hook)
            await asyncio.wait_for(hook_started.wait(), 1)
            (handle,) = worker.active_handlers
            self.assertFalse((await worker.drain(timeout=0.01)).complete)
            self.assertFalse(handle.done)
            release_hook.set()
            outcome = await handle.wait(timeout=1)
            self.assertIs(outcome.error, handler_error)
            self.assertIs(outcome.failure_hook_error, hook_error)
            self.assertTrue((await worker.drain()).complete)

    async def test_concurrent_handlers_remain_concurrent(self):
        handler, first_started, release, calls = self.blocked_handler()
        second_started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def concurrent_handler(job_id, payload, actor):
            if job_id == 1:
                handler(job_id, payload, actor)
            else:
                loop.call_soon_threadsafe(second_started.set)

        worker, task, pool = self.start_worker(
            concurrent_handler,
            messages=[queued_message(1), queued_message(2)],
        )
        await asyncio.wait_for(first_started.wait(), 1)
        await asyncio.wait_for(second_started.wait(), 1)
        self.assertFalse(release.is_set())
        result = await worker.drain(timeout=0.01)
        self.assertEqual([handle.message.msg_id for handle in result.unresolved], [1])
        self.assertEqual(pool.deleted, [1, 2])
        release.set()
        self.assertTrue((await worker.drain(timeout=1)).complete)

    async def test_stop_wakes_poll_delay_and_leaves_unselected_work_queued(self):
        pool = FakePool([queued_message()])
        worker = QueueWorker(get_pool=lambda: pool, poll_seconds=3600)
        task = asyncio.create_task(worker.run())
        self.workers.append((worker, task))
        await asyncio.sleep(0)
        worker.stop_polling()
        await asyncio.wait_for(task, 1)
        self.assertEqual(pool.deleted, [])
        self.assertEqual(len(pool.messages), 1)
        self.assertTrue((await worker.drain(timeout=0)).complete)
        with self.assertRaisesRegex(RuntimeError, "only be run once"):
            await worker.run()

    async def test_factory_retains_completion_through_repository_failure_hook(self):
        handler, started, release, calls = self.blocked_handler()
        loop = asyncio.get_running_loop()
        hook_started = asyncio.Event()
        release_hook = threading.Event()
        self.releases.append(release_hook)

        class Repo:
            def update_job(repo, job_id, status):
                self.assertEqual((job_id, status), (1, "FAILED"))
                loop.call_soon_threadsafe(hook_started.set)
                release_hook.wait(timeout=5)

        def failing_handler(*args):
            handler(*args)
            raise ValueError("failed")

        pool = FakePool([queued_message()])
        worker = create_queue_worker(
            get_pool=lambda: pool, get_repo=Repo, handlers={"TEST": failing_handler}
        )
        with (
            patch.object(worker, "_poll_seconds", 0.001),
            patch("cpkit.jobs.worker.logger.exception"),
        ):
            task = asyncio.create_task(worker())
            self.workers.append((worker, task))
            await asyncio.wait_for(started.wait(), 1)
            (handle,) = worker.active_handlers
            release.set()
            await asyncio.wait_for(hook_started.wait(), 1)
            result = await worker.drain(timeout=0.01)
            self.assertEqual(result.unresolved, (handle,))
            release_hook.set()
            self.assertTrue((await worker.drain(timeout=1)).complete)
            self.assertIsInstance(handle.result().error, ValueError)

    async def test_poller_error_retains_previously_submitted_handler(self):
        from concurrent.futures import ThreadPoolExecutor

        handler, started, release, calls = self.blocked_handler()
        original_submit = ThreadPoolExecutor.submit
        submissions = 0

        def submit(executor, *args, **kwargs):
            nonlocal submissions
            submissions += 1
            if submissions > 1:
                raise RuntimeError("closed")
            return original_submit(executor, *args, **kwargs)

        with (
            patch.object(
                ThreadPoolExecutor, "submit", autospec=True, side_effect=submit
            ),
            patch("cpkit.jobs.worker.logger.exception"),
        ):
            worker, task, pool = self.start_worker(
                handler,
                messages=[queued_message(1), queued_message(2)],
            )
            await asyncio.wait_for(started.wait(), 1)
            (handle,) = worker.active_handlers
            with self.assertRaises(QueueDispatchError):
                await task
        self.assertEqual((await worker.drain(timeout=0.01)).unresolved, (handle,))
        release.set()
        self.assertTrue((await worker.drain(timeout=1)).complete)
        self.assertEqual(len(calls), 1)

    async def test_startup_error_still_allows_clean_drain(self):
        def bad_config():
            raise ValueError("bad recurrence")

        worker = QueueWorker(get_pool=lambda: None, recurring_messages=bad_config)
        with self.assertRaisesRegex(ValueError, "bad recurrence"):
            await worker.run()
        self.assertTrue((await worker.drain(timeout=0)).complete)

    async def test_drain_before_start_prevents_startup_and_dispatch(self):
        def forbidden():
            self.fail("stopped worker initialized after drain")

        worker = QueueWorker(get_pool=forbidden, recurring_messages=forbidden)
        self.assertTrue((await worker.drain(timeout=0)).complete)
        await worker.run()

    async def test_drain_leaves_default_executor_usable(self):
        loop = asyncio.get_running_loop()
        self.assertEqual(await loop.run_in_executor(None, lambda: 1), 1)
        handler, started, release, calls = self.blocked_handler()
        worker, task, pool = self.start_worker(handler)
        await asyncio.wait_for(started.wait(), 1)
        release.set()
        self.assertTrue((await worker.drain(timeout=1)).complete)
        self.assertEqual(await loop.run_in_executor(None, lambda: 2), 2)

    async def test_standalone_convenience_waits_for_handler_even_on_repeated_cancellation(
        self,
    ):
        handler, started, release, calls = self.blocked_handler()
        pool = FakePool([queued_message()])
        task = asyncio.create_task(
            run_queue_worker(
                get_pool=lambda: pool,
                handlers={"TEST": handler},
                poll_seconds=0.001,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.01)
            self.assertFalse(task.done())
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        self.assertEqual(len(calls), 1)
