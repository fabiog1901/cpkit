"""Actual bundle/lifespan tests. Require a disposable PostgreSQL database."""

import asyncio
import base64
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg
from pydantic import BaseModel

from cpkit import CPKitRepo, create_cpkit_app, create_cpkit_bundle
from cpkit.app import AppShutdownIncomplete
from cpkit.db import close_db, get_pool
from cpkit.jobs import configure_recurring_messages
from cpkit.playbooks import configure_playbook_run_options

DB_URL = os.getenv("CPKIT_WORKER_INTEGRATION_DB_URL")


class Payload(BaseModel):
    value: int


@unittest.skipUnless(
    DB_URL, "CPKIT_WORKER_INTEGRATION_DB_URL requires a disposable PostgreSQL database"
)
class AppDatabaseLifecycleTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute(
                (Path(__file__).parents[1] / "cpkit/resources/ddl.sql").read_text()
            )
            conn.execute(
                "CREATE TABLE cpkit.shutdown_test_state (job_id bigint PRIMARY KEY, value int)"
            )

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute("DROP TABLE cpkit.shutdown_test_state")

    def setUp(self):
        key_environment = patch.dict(
            os.environ, {"CPKIT_MASTER_KEY": base64.b64encode(os.urandom(32)).decode()}
        )
        key_environment.start()
        self.addCleanup(key_environment.stop)
        self.apps = []
        self.release_handler = threading.Event()
        self.release_hook = threading.Event()
        self.events = []
        self.calls = []
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute("TRUNCATE cpkit.mq, cpkit.jobs CASCADE")
            self.job_id = conn.execute("""
                INSERT INTO cpkit.mq (msg_type, msg_data, created_by, start_after)
                VALUES ('TEST', '{"value": 42}', 'actual-actor', now() - interval '1s')
                RETURNING msg_id
            """).fetchone()[0]
            conn.execute(
                "INSERT INTO cpkit.jobs (job_id, job_type, status) VALUES (%s, 'TEST', 'QUEUED')",
                (self.job_id,),
            )

    async def asyncTearDown(self):
        self.release_handler.set()
        self.release_hook.set()
        for app in self.apps:
            runtime = getattr(app.state, "cpkit_runtime", None)
            if runtime is not None:
                self.assertTrue((await runtime.shutdown(timeout=3)).complete)
        close_db()
        configure_recurring_messages()
        configure_playbook_run_options()
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute("TRUNCATE cpkit.mq, cpkit.jobs CASCADE")
            conn.execute("TRUNCATE cpkit.shutdown_test_state")

    def setup_app(self, *, fails=False, shutdown_timeout=None):
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        hook_started = asyncio.Event()
        owner = self

        class Repo(CPKitRepo):
            def update_job(self, job_id, status):
                loop.call_soon_threadsafe(hook_started.set)
                owner.release_hook.wait(timeout=5)
                super().update_job(job_id, status)
                owner.events.append("failure_persisted")

        def handler(job_id, payload, actor):
            self.calls.append((job_id, payload, actor))
            loop.call_soon_threadsafe(started.set)
            self.release_handler.wait(timeout=5)
            with get_pool().connection() as conn:
                conn.execute(
                    "INSERT INTO cpkit.shutdown_test_state VALUES (%s, %s)",
                    (job_id, payload.value),
                )
            self.events.append("handler_used_pool")
            if fails:
                raise ValueError("controlled handler failure")

        bundle = create_cpkit_bundle(
            command_models={"TEST": Payload}, command_handlers={"TEST": handler}
        )
        app = create_cpkit_app(
            title="test",
            version="1",
            db_url=DB_URL,
            get_repo=Repo,
            bundles=(bundle,),
            shutdown_timeout=shutdown_timeout,
        )
        self.apps.append(app)
        return app, bundle.queue_worker, started, hook_started

    def close_pool(self):
        self.events.append("close")
        close_db()

    def verify_persisted(self, *, failed=False):
        with psycopg.connect(DB_URL) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT value FROM cpkit.shutdown_test_state WHERE job_id=%s",
                    (self.job_id,),
                ).fetchone(),
                (42,),
            )
            if failed:
                self.assertEqual(
                    conn.execute(
                        "SELECT status FROM cpkit.jobs WHERE job_id=%s", (self.job_id,)
                    ).fetchone(),
                    ("FAILED",),
                )
        self.assertEqual(self.calls, [(self.job_id, Payload(value=42), "actual-actor")])

    async def test_real_handler_can_use_pool_until_lifespan_drain_completes(self):
        app, worker, started, _ = self.setup_app()
        with (
            patch("cpkit.app.configure_logging"),
            patch("cpkit.app.close_db", side_effect=self.close_pool),
            patch.object(worker, "_poll_seconds", 0.001),
        ):
            context = app.router.lifespan_context(app)
            await context.__aenter__()
            await asyncio.wait_for(started.wait(), 2)
            pool = get_pool()
            closing = asyncio.create_task(context.__aexit__(None, None, None))
            await asyncio.sleep(0.01)
            self.assertFalse(pool.closed)
            self.assertTrue(worker.polling_stopped)
            self.release_handler.set()
            await asyncio.wait_for(closing, 2)
        self.assertTrue(pool.closed)
        self.assertTrue(app.state.cpkit_runtime.status.complete)
        self.assertEqual(self.events, ["handler_used_pool", "close"])
        self.verify_persisted()

    async def test_timeout_keeps_real_pool_until_handler_and_failure_update_finish(
        self,
    ):
        app, worker, started, hook_started = self.setup_app(
            fails=True, shutdown_timeout=0.01
        )
        with (
            patch("cpkit.app.configure_logging"),
            patch("cpkit.app.close_db", side_effect=self.close_pool),
            patch.object(worker, "_poll_seconds", 0.001),
            patch("cpkit.jobs.worker.logger.exception"),
        ):
            context = app.router.lifespan_context(app)
            await context.__aenter__()
            await asyncio.wait_for(started.wait(), 2)
            pool = get_pool()
            (handle,) = worker.active_handlers
            with self.assertRaises(AppShutdownIncomplete) as caught:
                await context.__aexit__(None, None, None)
            self.assertEqual(caught.exception.result.unresolved, (handle,))
            self.assertIs(get_pool(), pool)
            self.assertFalse(pool.closed)
            self.release_handler.set()
            await asyncio.wait_for(hook_started.wait(), 2)
            self.assertFalse(
                (await app.state.cpkit_runtime.shutdown(timeout=0.01)).complete
            )
            self.assertFalse(handle.done)
            self.assertFalse(pool.closed)
            self.release_hook.set()
            self.assertTrue(
                (await app.state.cpkit_runtime.shutdown(timeout=2)).complete
            )
        self.assertTrue(pool.closed)
        self.assertIsInstance(handle.result().error, ValueError)
        self.assertIsNone(handle.result().failure_hook_error)
        self.assertEqual(
            self.events, ["handler_used_pool", "failure_persisted", "close"]
        )
        self.verify_persisted(failed=True)

    async def test_cancelled_shutdown_keeps_real_pool_for_later_join(self):
        app, worker, started, _ = self.setup_app()
        with (
            patch("cpkit.app.configure_logging"),
            patch("cpkit.app.close_db", side_effect=self.close_pool),
            patch.object(worker, "_poll_seconds", 0.001),
        ):
            context = app.router.lifespan_context(app)
            await context.__aenter__()
            await asyncio.wait_for(started.wait(), 2)
            pool = get_pool()
            closing = asyncio.create_task(context.__aexit__(None, None, None))
            await asyncio.sleep(0.01)
            closing.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await closing
            self.assertFalse(pool.closed)
            self.assertIs(app.state.cpkit_runtime.pool, pool)
            self.assertEqual(len(app.state.cpkit_runtime.status.unresolved), 1)
            self.release_handler.set()
            self.assertTrue(
                (await app.state.cpkit_runtime.shutdown(timeout=2)).complete
            )
        self.assertTrue(pool.closed)
        self.verify_persisted()
