"""Registered bundle consumer tests; require a disposable PostgreSQL database."""

import asyncio
import os
import threading
import unittest
from enum import StrEnum
from pathlib import Path
from unittest.mock import Mock, patch

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, ValidationError

from cpkit.bundle import create_cpkit_bundle
from cpkit.jobs import RecurringMessage, configure_recurring_messages

DB_URL = os.getenv("CPKIT_WORKER_INTEGRATION_DB_URL")


class Command(StrEnum):
    TEST = "TEST"


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


@unittest.skipUnless(
    DB_URL, "CPKIT_WORKER_INTEGRATION_DB_URL requires a disposable PostgreSQL database"
)
class ScopedBundleIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute(
                (Path(__file__).parents[1] / "cpkit/resources/ddl.sql").read_text()
            )
        cls.pool = ConnectionPool(DB_URL, kwargs={"autocommit": True}, open=True)
        cls.pool.wait()

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()

    def setUp(self):
        self.workers = []
        self.releases = []
        with self.pool.connection() as conn:
            conn.execute("TRUNCATE cpkit.mq")
        configure_recurring_messages((RecurringMessage("TEST", 300),))

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        for worker in self.workers:
            self.assertTrue((await worker.drain(timeout=3)).complete)
        configure_recurring_messages()
        with self.pool.connection() as conn:
            conn.execute("TRUNCATE cpkit.mq")

    def bundle(self, handler, *, repo=None, **kwargs):
        with (
            patch("cpkit.bundle.get_pool", return_value=self.pool),
            patch("cpkit.bundle.get_repo", return_value=repo or Mock()),
        ):
            bundle = create_cpkit_bundle(
                command_models={Command.TEST: Payload},
                command_handlers={Command.TEST: handler},
                **kwargs,
            )
        self.workers.append(bundle.queue_worker)
        self.assertIs(bundle.background_tasks[0], bundle.queue_worker)
        return bundle

    def enqueue(
        self,
        *,
        msg_type="TEST",
        payload=None,
        actor="original-actor",
        recurring=False,
        due=True,
    ):
        with self.pool.connection() as conn:
            return conn.execute(
                """
                INSERT INTO cpkit.mq (msg_type, msg_data, created_by, is_recurring, start_after)
                VALUES (%s, %s, %s, %s, now() + (%s * interval '1s'))
                RETURNING msg_id
            """,
                (
                    msg_type,
                    Jsonb({"value": 7} if payload is None else payload),
                    actor,
                    recurring,
                    -10 if due else 300,
                ),
            ).fetchone()[0]

    def snapshot(self):
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM cpkit.mq ORDER BY msg_id").fetchall()

    async def test_registered_typed_handler_actor_and_followups_are_preserved(self):
        unrelated = self.enqueue()
        recurring = self.enqueue(recurring=True)
        maintenance = self.enqueue(
            msg_type="FAIL_ZOMBIE_JOBS", payload={}, recurring=True
        )
        selected = self.enqueue()
        before = {row[0]: row for row in self.snapshot()}
        calls = []
        followups = []

        def handler(job_id, payload, actor):
            calls.append((job_id, payload, actor))
            followups.append(self.enqueue())

        bundle = self.bundle(handler)
        worker = bundle.queue_worker
        handle = await worker.dispatch_one(
            message_id=selected,
            expected_type="TEST",
            expected_actor="original-actor",
        )
        self.assertIsNotNone(handle)
        self.assertIsInstance(handle.payload, Payload)
        self.assertIsNone((await handle.wait(timeout=1)).error)
        self.assertIs(calls[0][1], handle.payload)
        self.assertEqual(calls, [(selected, Payload(value=7), "original-actor")])
        self.assertEqual(handle.message.msg_id, selected)
        self.assertEqual(handle.message.msg_data, {"value": 7})
        self.assertTrue((await worker.drain(timeout=1)).complete)
        after = {row[0]: row for row in self.snapshot()}
        self.assertEqual(set(after), {unrelated, recurring, maintenance, *followups})
        for job_id in (unrelated, recurring, maintenance):
            self.assertEqual(before[job_id], after[job_id])
        with self.assertRaisesRegex(RuntimeError, "only be run once"):
            await worker.dispatch_one(message_id=followups[0])

    async def test_rejected_expectations_not_due_and_absent_ids_leave_queue_unchanged(
        self,
    ):
        selected = self.enqueue()
        future = self.enqueue(due=False)
        before = self.snapshot()
        handler = Mock()
        for options in (
            {"message_id": selected, "expected_type": "OTHER"},
            {"message_id": selected, "expected_actor": "another-actor"},
            {"message_id": future},
            {"message_id": -1},
        ):
            worker = self.bundle(handler).queue_worker
            self.assertIsNone(await worker.dispatch_one(**options))
            self.assertEqual(self.snapshot(), before)
        handler.assert_not_called()

    async def test_malformed_foreign_and_unknown_work_is_not_deleted(self):
        handler = Mock()
        for msg_type, payload, error in (
            ("TEST", {"value": "not-an-integer"}, ValidationError),
            ("TEST", {"foreign": "payload"}, ValidationError),
            ("OTHER", {"value": 7}, ValueError),
        ):
            selected = self.enqueue(msg_type=msg_type, payload=payload)
            before = self.snapshot()
            worker = self.bundle(handler).queue_worker
            with self.assertRaises(error):
                await worker.dispatch_one(message_id=selected)
            self.assertEqual(self.snapshot(), before)
        handler.assert_not_called()

    async def test_recurring_requires_opt_in_and_uses_registered_schedule(self):
        selected = self.enqueue(recurring=True)
        unrelated = self.enqueue()
        handler = Mock()
        before = self.snapshot()
        self.assertIsNone(
            await self.bundle(handler).queue_worker.dispatch_one(message_id=selected)
        )
        self.assertEqual(self.snapshot(), before)
        worker = self.bundle(handler).queue_worker
        handle = await worker.dispatch_one(message_id=selected, include_recurring=True)
        self.assertTrue(handle.message.is_recurring)
        self.assertIsNone((await handle.wait(timeout=1)).error)
        self.assertTrue((await worker.drain(timeout=1)).complete)
        handler.assert_called_once_with(selected, Payload(value=7), "original-actor")
        with self.pool.connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT start_after > now() FROM cpkit.mq WHERE msg_id=%s",
                    (selected,),
                ).fetchone(),
                (True,),
            )
        self.assertEqual(
            next(row for row in self.snapshot() if row[0] == unrelated),
            next(row for row in before if row[0] == unrelated),
        )

    async def test_unconfigured_recurring_and_invalid_recurring_payload_remain_unchanged(
        self,
    ):
        for msg_type, payload, error in (
            ("UNREGISTERED_RECURRING", {"value": 7}, None),
            ("TEST", {"value": "invalid"}, ValidationError),
        ):
            selected = self.enqueue(msg_type=msg_type, payload=payload, recurring=True)
            before = self.snapshot()
            handler = Mock()
            worker = self.bundle(handler).queue_worker
            if error:
                with self.assertRaises(error):
                    await worker.dispatch_one(
                        message_id=selected, include_recurring=True
                    )
            else:
                self.assertIsNone(
                    await worker.dispatch_one(
                        message_id=selected, include_recurring=True
                    )
                )
            self.assertEqual(self.snapshot(), before)
            handler.assert_not_called()

    async def test_custom_parser_and_resolver_receive_same_selected_message(self):
        selected = self.enqueue(msg_type="CUSTOM")
        parsed = Payload(value=99)
        parser = Mock(return_value=parsed)
        handler = Mock()
        resolver = Mock(return_value=handler)
        worker = self.bundle(
            Mock(), parse_queue_message=parser, resolve_queue_handler=resolver
        ).queue_worker
        handle = await worker.dispatch_one(message_id=selected)
        await handle.wait(timeout=1)
        self.assertIs(handle.payload, parsed)
        self.assertIs(parser.call_args.args[0], handle.message)
        self.assertIs(resolver.call_args.args[0], handle.message)
        handler.assert_called_once_with(selected, parsed, "original-actor")

    async def test_locked_and_changed_identity_refuse_without_fallback(self):
        selected = self.enqueue()
        unrelated = self.enqueue()
        handler = Mock()
        with psycopg.connect(DB_URL) as other:
            other.execute(
                "UPDATE cpkit.mq SET created_by='new-actor', msg_data=%s WHERE msg_id=%s",
                (Jsonb({"value": 88}), selected),
            )
            # Selection cannot claim an externally locked row, and must not
            # fall back to another due row even with recurring enabled.
            worker = self.bundle(handler).queue_worker
            self.assertIsNone(
                await worker.dispatch_one(message_id=selected, include_recurring=True)
            )
        before = self.snapshot()
        worker = self.bundle(handler).queue_worker
        self.assertIsNone(
            await worker.dispatch_one(
                message_id=selected, expected_actor="original-actor"
            )
        )
        self.assertEqual(self.snapshot(), before)
        handler.assert_not_called()
        worker = self.bundle(handler).queue_worker
        handle = await worker.dispatch_one(
            message_id=selected, expected_actor="new-actor"
        )
        await handle.wait(timeout=1)
        handler.assert_called_once_with(selected, Payload(value=88), "new-actor")
        self.assertEqual([row[0] for row in self.snapshot()], [unrelated])

    async def test_single_dispatch_reuses_timeout_and_later_drain(self):
        selected = self.enqueue()
        release = threading.Event()
        self.releases.append(release)

        def handler(*args):
            release.wait(timeout=5)

        worker = self.bundle(handler).queue_worker
        handle = await worker.dispatch_one(message_id=selected)
        self.assertFalse((await worker.drain(timeout=0.01)).complete)
        self.assertEqual(worker.active_handlers, (handle,))
        release.set()
        self.assertTrue((await worker.drain(timeout=1)).complete)
        self.assertTrue(handle.done)

    async def test_default_background_factory_uses_registered_models_for_normal_and_recurring(
        self,
    ):
        loop = asyncio.get_running_loop()
        for recurring in (False, True):
            with self.pool.connection() as conn:
                conn.execute("TRUNCATE cpkit.mq")
            selected = self.enqueue(recurring=recurring)
            observed = []

            def handler(job_id, payload, actor):
                observed.append((job_id, payload, actor))
                loop.call_soon_threadsafe(worker.stop_polling)

            bundle = self.bundle(handler)
            worker = bundle.queue_worker
            with patch.object(worker, "_poll_seconds", 0.001):
                poller = asyncio.create_task(bundle.background_tasks[0]())
                try:
                    await asyncio.wait_for(poller, timeout=1)
                finally:
                    worker.stop_polling()
                    if not poller.done():
                        poller.cancel()
                    try:
                        await poller
                    except asyncio.CancelledError:
                        pass
            self.assertTrue((await worker.drain(timeout=1)).complete)
            self.assertEqual(observed, [(selected, Payload(value=7), "original-actor")])

    async def test_framework_maintenance_uses_builtin_handler_and_parser(self):
        selected = self.enqueue(msg_type="FAIL_ZOMBIE_JOBS", payload={}, recurring=True)
        repo = Mock()
        application_handler = Mock()
        worker = self.bundle(application_handler, repo=repo).queue_worker
        handle = await worker.dispatch_one(message_id=selected, include_recurring=True)
        self.assertIsNone((await handle.wait(timeout=1)).error)
        self.assertEqual(handle.payload, {})
        repo.fail_zombie_jobs.assert_called_once_with()
        application_handler.assert_not_called()

    async def test_invalid_selection_cannot_turn_into_unrestricted_dispatch(self):
        selected = self.enqueue()
        handler = Mock()
        worker = self.bundle(handler).queue_worker
        for invalid in (None, True, "1"):
            with self.assertRaises(TypeError):
                await worker.dispatch_one(message_id=invalid)
        self.assertEqual([row[0] for row in self.snapshot()], [selected])
        handler.assert_not_called()
