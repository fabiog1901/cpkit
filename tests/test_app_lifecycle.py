import asyncio
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from test_app_playbook_options import FakeSettingsRepo
from test_jobs_lifecycle import queued_message
from test_jobs_worker import FakePool

from cpkit.app import AppShutdownIncomplete, create_cpkit_app
from cpkit.bundle import CpkitBundle
from cpkit.jobs import QueueWorker, configure_recurring_messages
from cpkit.playbooks import configure_playbook_run_options


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.apps = []
        self.releases = []
        self.events = []
        self.repo = FakeSettingsRepo()
        self.pool = FakePool([queued_message()])
        self.initialize = self.patches.enter_context(
            patch("cpkit.app.initialize_postgres")
        )
        self.patches.enter_context(patch("cpkit.app.configure_repository"))
        self.patches.enter_context(
            patch("cpkit.app.get_configured_repo", return_value=self.repo)
        )
        self.current_pool = self.patches.enter_context(
            patch("cpkit.app.get_pool", return_value=self.pool)
        )
        self.patches.enter_context(patch("cpkit.app.configure_logging"))
        self.close = self.patches.enter_context(
            patch("cpkit.app.close_db", side_effect=lambda: self.events.append("close"))
        )

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        for app in self.apps:
            runtime = getattr(app.state, "cpkit_runtime", None)
            if runtime is not None:
                self.assertTrue((await runtime.shutdown(timeout=2)).complete)
        self.patches.close()
        configure_recurring_messages()
        configure_playbook_run_options()

    def blocked_worker(self):
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        self.releases.append(release)
        calls = []

        def handler(*args):
            calls.append(args)
            loop.call_soon_threadsafe(started.set)
            release.wait(timeout=5)
            self.assertFalse(self.close.called)
            with self.pool.connection():
                self.events.append("handler_used_pool")

        return (
            QueueWorker(
                get_pool=lambda: self.pool,
                handlers={"TEST": handler},
                poll_seconds=0.001,
            ),
            started,
            release,
            calls,
        )

    def app(self, worker=None, **kwargs):
        bundles = ()
        if worker is not None:
            bundles = (
                CpkitBundle(
                    auth=Mock(),
                    routers=(),
                    startup_hooks=(),
                    background_tasks=(worker,),
                    queue_worker=worker,
                ),
            )
        app = create_cpkit_app(
            title="test",
            version="1",
            db_url="test",
            get_repo=lambda: self.repo,
            bundles=bundles,
            **kwargs,
        )
        self.apps.append(app)
        return app

    async def test_lifespan_stops_and_drains_before_pool_close(self):
        worker, started, release, calls = self.blocked_worker()
        app = self.app(worker)
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        await asyncio.wait_for(started.wait(), 1)
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.sleep(0.01)
        self.assertTrue(worker.polling_stopped)
        self.close.assert_not_called()
        self.assertEqual(app.state.cpkit_runtime.workers, (worker,))
        release.set()
        await asyncio.wait_for(closing, 1)
        self.assertEqual(self.events, ["handler_used_pool", "close"])
        self.assertTrue(app.state.cpkit_runtime.status.complete)
        self.close.assert_called_once_with()
        self.assertEqual(len(calls), 1)

    async def test_timeout_preserves_pool_handle_and_supports_later_shutdown(self):
        worker, started, release, calls = self.blocked_worker()
        app = self.app(worker, shutdown_timeout=0.01)
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        await asyncio.wait_for(started.wait(), 1)
        (handle,) = worker.active_handlers
        with self.assertRaises(AppShutdownIncomplete) as caught:
            await context.__aexit__(None, None, None)
        runtime = app.state.cpkit_runtime
        self.assertIs(caught.exception.runtime, runtime)
        self.assertIs(runtime.pool, self.pool)
        self.assertEqual(caught.exception.result.unresolved, (handle,))
        self.close.assert_not_called()
        self.assertFalse(handle.done)
        with self.assertRaisesRegex(RuntimeError, "unfinished shutdown"):
            async with app.router.lifespan_context(app):
                self.fail("replaced unfinished runtime")
        self.assertIs(app.state.cpkit_runtime, runtime)
        release.set()
        self.assertTrue((await runtime.shutdown(timeout=1)).complete)
        self.assertTrue((await runtime.shutdown(timeout=0)).complete)
        self.assertEqual(len(calls), 1)
        self.close.assert_called_once_with()

    async def test_cancellation_during_shutdown_retains_context(self):
        worker, started, release, calls = self.blocked_worker()
        app = self.app(worker)
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        await asyncio.wait_for(started.wait(), 1)
        (handle,) = worker.active_handlers
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.sleep(0.01)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.close.assert_not_called()
        self.assertEqual(app.state.cpkit_runtime.status.unresolved, (handle,))
        release.set()
        self.assertTrue((await app.state.cpkit_runtime.shutdown(timeout=1)).complete)

    async def test_cancelled_lifespan_body_preserves_pool_for_later_drain(self):
        worker, started, release, calls = self.blocked_worker()
        app = self.app(worker)

        async def host():
            async with app.router.lifespan_context(app):
                await asyncio.Event().wait()

        hosting = asyncio.create_task(host())
        await asyncio.wait_for(started.wait(), 1)
        hosting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await hosting
        self.close.assert_not_called()
        self.assertFalse(app.state.cpkit_runtime.status.complete)
        release.set()
        self.assertTrue((await app.state.cpkit_runtime.shutdown(timeout=1)).complete)

    async def test_body_error_drains_then_preserves_original_error(self):
        worker, started, release, calls = self.blocked_worker()
        app = self.app(worker)
        failure = ValueError("body failed")

        async def host():
            async with app.router.lifespan_context(app):
                await started.wait()
                raise failure

        hosting = asyncio.create_task(host())
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(0.01)
        self.close.assert_not_called()
        release.set()
        with self.assertRaises(ValueError) as caught:
            await hosting
        self.assertIs(caught.exception, failure)
        self.close.assert_called_once()

    async def test_startup_hook_failure_drains_already_dispatched_work(self):
        worker, started, release, calls = self.blocked_worker()

        async def startup():
            await worker.dispatch_one(message_id=1)
            raise RuntimeError("startup failed")

        # The worker has already dispatched during startup and is retained by
        # the bundle, even though its background factory was never started.
        app = self.app(worker, startup_hooks=(startup,))
        entering = asyncio.create_task(app.router.lifespan_context(app).__aenter__())
        await asyncio.wait_for(started.wait(), 1)
        self.close.assert_not_called()
        release.set()
        with self.assertRaisesRegex(RuntimeError, "startup failed"):
            await entering
        self.assertTrue(app.state.cpkit_runtime.status.complete)
        self.close.assert_called_once()

    async def test_background_failure_is_surfaced_after_handler_drain(self):
        worker, started, release, calls = self.blocked_worker()
        failure = ValueError("background failed")

        async def fail():
            raise failure

        app = self.app(worker, background_tasks=(fail,))
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        await asyncio.wait_for(started.wait(), 1)
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.sleep(0.01)
        self.close.assert_not_called()
        release.set()
        with self.assertRaises(ValueError) as caught:
            await closing
        self.assertIs(caught.exception, failure)
        self.assertEqual(app.state.cpkit_runtime.status.task_errors, (failure,))
        self.close.assert_called_once()

    async def test_partial_background_factory_failure_cleans_previous_tasks(self):
        def fail():
            raise ValueError("factory failed")

        app = self.app(background_tasks=(lambda: asyncio.sleep(3600), fail))
        with self.assertRaisesRegex(ValueError, "factory failed"):
            async with app.router.lifespan_context(app):
                self.fail("startup unexpectedly succeeded")
        self.assertTrue(app.state.cpkit_runtime.status.complete)
        self.close.assert_called_once()

    async def test_early_initialization_failure_and_no_handler_exit_close_pool(self):
        for fails in (True, False):
            self.initialize.side_effect = (
                RuntimeError("initialize failed") if fails else None
            )
            app = self.app()
            if fails:
                with self.assertRaisesRegex(RuntimeError, "initialize failed"):
                    async with app.router.lifespan_context(app):
                        self.fail("unexpected startup")
            else:
                async with app.router.lifespan_context(app):
                    pass
            self.assertTrue(app.state.cpkit_runtime.status.complete)
        self.assertEqual(self.close.call_count, 2)

    async def test_timed_out_background_cleanup_is_not_cancelled_again_on_retry(self):
        ready = asyncio.Event()
        release = asyncio.Event()

        async def background():
            try:
                ready.set()
                await asyncio.Event().wait()
            finally:
                await release.wait()

        app = self.app(background_tasks=(background,), shutdown_timeout=0.01)
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        await ready.wait()
        with self.assertRaises(AppShutdownIncomplete) as caught:
            await context.__aexit__(None, None, None)
        self.assertEqual(len(caught.exception.result.pending_tasks), 1)
        self.close.assert_not_called()
        release.set()
        self.assertTrue((await app.state.cpkit_runtime.shutdown(timeout=1)).complete)

    async def test_close_timeout_error_propagates_and_can_be_retried(self):
        app = self.app()
        self.close.side_effect = [TimeoutError("pool close failed"), None]
        with self.assertRaisesRegex(TimeoutError, "pool close failed"):
            async with app.router.lifespan_context(app):
                pass
        self.assertFalse(app.state.cpkit_runtime.status.pool_closed)
        self.assertTrue((await app.state.cpkit_runtime.shutdown(timeout=1)).complete)

    async def test_body_and_background_errors_are_both_preserved(self):
        body_error = ValueError("body failed")
        background_error = RuntimeError("background failed")
        failed = asyncio.Event()

        async def background():
            failed.set()
            raise background_error

        app = self.app(background_tasks=(background,))
        with self.assertRaises(ExceptionGroup) as caught:
            async with app.router.lifespan_context(app):
                await failed.wait()
                raise body_error
        self.assertEqual(caught.exception.exceptions, (body_error, background_error))
        self.close.assert_called_once()

    async def test_retained_runtime_does_not_close_a_replacement_pool(self):
        app = self.app()
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        self.current_pool.return_value = object()
        try:
            with self.assertRaisesRegex(RuntimeError, "Shared pool changed"):
                await context.__aexit__(None, None, None)
            self.close.assert_not_called()
            self.assertIs(app.state.cpkit_runtime.pool, self.pool)
        finally:
            self.current_pool.return_value = self.pool
        self.assertTrue((await app.state.cpkit_runtime.shutdown(timeout=1)).complete)

    async def test_direct_queue_background_factory_is_drained(self):
        worker, started, release, calls = self.blocked_worker()
        app = self.app(background_tasks=(worker,))
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        await asyncio.wait_for(started.wait(), 1)
        self.assertEqual(app.state.cpkit_runtime.workers, (worker,))
        release.set()
        await context.__aexit__(None, None, None)
        self.assertTrue(app.state.cpkit_runtime.status.complete)
        self.assertEqual(self.events, ["handler_used_pool", "close"])

    async def test_background_iterable_is_consumed_after_startup_hooks(self):
        def startup():
            self.events.append("startup")

        def factories():
            self.assertEqual(self.events, ["startup"])
            yield lambda: asyncio.sleep(0)

        app = self.app(startup_hooks=(startup,), background_tasks=factories())
        async with app.router.lifespan_context(app):
            pass
        self.assertEqual(self.events, ["startup", "close"])
