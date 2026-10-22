"""Consumer tests. Use only a disposable database: this suite clears cpkit.mq."""

import asyncio
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg_pool import ConnectionPool

from cpkit.jobs import QueueDispatchError, RecurringMessage, run_queue_worker
from cpkit.jobs.worker import _claim_and_prepare_dispatch

DB_URL = os.getenv("CPKIT_WORKER_INTEGRATION_DB_URL")


@unittest.skipUnless(
    DB_URL, "CPKIT_WORKER_INTEGRATION_DB_URL requires a disposable PostgreSQL database"
)
class ConsumerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute(
                (Path(__file__).parents[1] / "cpkit/resources/ddl.sql").read_text()
            )
            conn.execute("""
                CREATE OR REPLACE FUNCTION cpkit.reject_test_claim()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'test commit rejection' USING ERRCODE = '40001';
                END $$;
                CREATE TABLE cpkit.worker_serialization_test (id int PRIMARY KEY, value int);
                INSERT INTO cpkit.worker_serialization_test VALUES (1, 0);
            """)
        cls.pool = ConnectionPool(DB_URL, kwargs={"autocommit": True})
        cls.pool.wait()

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute("DROP TABLE cpkit.worker_serialization_test")
            conn.execute("DROP FUNCTION cpkit.reject_test_claim()")

    def setUp(self):
        with self.pool.connection() as conn:
            conn.execute("TRUNCATE cpkit.mq")

    def tearDown(self):
        with self.pool.connection() as conn:
            conn.execute("DROP TRIGGER IF EXISTS reject_claim ON cpkit.mq")
            conn.execute("TRUNCATE cpkit.mq")

    def enqueue(self, *, recurring=False):
        with self.pool.connection() as conn:
            return conn.execute(
                """
                INSERT INTO cpkit.mq (msg_type, created_by, start_after, is_recurring)
                VALUES ('TEST', 'actual-actor', now() - interval '1s', %s)
                RETURNING msg_id
            """,
                (recurring,),
            ).fetchone()[0]

    def prepare(self, **kwargs):
        pool = kwargs.pop("pool", self.pool)
        return _claim_and_prepare_dispatch(
            get_pool=lambda: pool,
            recurring_configs={"TEST": RecurringMessage("TEST", 300)},
            handlers={"TEST": lambda *args: None},
            resolve_handler=None,
            parse_message=kwargs.pop("parse", None),
        )

    async def test_real_handler_sees_committed_delete_or_recurring_schedule(self):
        for recurring in (False, True):
            with self.pool.connection() as conn:
                conn.execute("TRUNCATE cpkit.mq")
            job_id = self.enqueue(recurring=recurring)
            done = threading.Event()
            observations = []
            failures = []

            def handler(actual_id, payload, actor):
                try:
                    with self.pool.connection() as conn:
                        row = conn.execute(
                            "SELECT start_after > now() FROM cpkit.mq WHERE msg_id = %s",
                            (actual_id,),
                        ).fetchone()
                    observations.append((actual_id, payload, actor, row))
                finally:
                    done.set()

            worker = asyncio.create_task(
                run_queue_worker(
                    get_pool=lambda: self.pool,
                    handlers={"TEST": handler},
                    handle_failure=lambda msg, err: failures.append(err),
                    recurring_messages=(RecurringMessage("TEST", 300),),
                    poll_seconds=0.001,
                )
            )
            try:
                self.assertTrue(await asyncio.to_thread(done.wait, 3))
            finally:
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker
            self.assertEqual(failures, [])
            self.assertEqual(
                observations,
                [(job_id, {}, "actual-actor", (True,) if recurring else None)],
            )

    def test_parse_refusal_rolls_back_real_delete_or_reschedule(self):
        for recurring in (False, True):
            job_id = self.enqueue(recurring=recurring)
            with self.pool.connection() as conn:
                before = conn.execute(
                    "SELECT * FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                ).fetchone()

            def refuse(message):
                raise ValueError("invalid payload")

            with self.assertRaises(ValueError):
                self.prepare(parse=refuse)
            with self.pool.connection() as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT * FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                    ).fetchone(),
                    before,
                )
                conn.execute("TRUNCATE cpkit.mq")

    def test_deferred_commit_rejection_keeps_row_and_never_submits(self):
        job_id = self.enqueue()
        with self.pool.connection() as conn:
            conn.execute("""
                CREATE CONSTRAINT TRIGGER reject_claim AFTER DELETE ON cpkit.mq
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION cpkit.reject_test_claim()
            """)
        with self.assertRaises(QueueDispatchError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.phase, "commit_rejected")
        self.assertEqual(caught.exception.__cause__.sqlstate, "40001")
        with self.pool.connection() as conn:
            self.assertIsNotNone(
                conn.execute(
                    "SELECT 1 FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                ).fetchone()
            )

    async def test_postcommit_executor_failure_does_not_restore_message(self):
        job_id = self.enqueue()
        with patch.object(
            asyncio.get_running_loop(),
            "run_in_executor",
            side_effect=RuntimeError("closed"),
        ) as submit:
            with self.assertRaises(QueueDispatchError) as caught:
                await run_queue_worker(
                    get_pool=lambda: self.pool,
                    handlers={"TEST": lambda *args: None},
                    poll_seconds=0,
                )
        self.assertEqual(caught.exception.phase, "submission")
        submit.assert_called_once()
        with self.pool.connection() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                ).fetchone()
            )

    async def test_lost_commit_acknowledgement_never_submits_or_replays(self):
        job_id = self.enqueue()
        real_pool = self.pool

        class UncertainPool:
            @contextmanager
            def connection(self):
                with real_pool.connection() as conn:

                    class UncertainConnection:
                        info = conn.info
                        cursor = conn.cursor

                        @contextmanager
                        def transaction(self):
                            with conn.transaction():
                                yield
                            # The server committed; the caller cannot confirm it.
                            raise psycopg.OperationalError(
                                "lost commit acknowledgement"
                            )

                    yield UncertainConnection()

        with patch.object(asyncio.get_running_loop(), "run_in_executor") as submit:
            with self.assertRaises(QueueDispatchError) as caught:
                await run_queue_worker(
                    get_pool=UncertainPool,
                    handlers={"TEST": lambda *args: None},
                    poll_seconds=0,
                )
        self.assertEqual(caught.exception.phase, "commit_unknown")
        self.assertEqual(caught.exception.message.msg_id, job_id)
        submit.assert_not_called()
        with self.pool.connection() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                ).fetchone()
            )

    async def test_handler_failure_hook_observes_committed_claim(self):
        job_id = self.enqueue()
        done = threading.Event()
        observations = []

        def handler(*args):
            raise ValueError("handler failed")

        def failure(message, err):
            try:
                with self.pool.connection() as conn:
                    row = conn.execute(
                        "SELECT 1 FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                    ).fetchone()
                observations.append((message.msg_id, str(err), row))
            finally:
                done.set()

        worker = asyncio.create_task(
            run_queue_worker(
                get_pool=lambda: self.pool,
                handlers={"TEST": handler},
                handle_failure=failure,
                poll_seconds=0.001,
            )
        )
        try:
            with patch("cpkit.jobs.worker.logger.exception"):
                self.assertTrue(await asyncio.to_thread(done.wait, 3))
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
        self.assertEqual(observations, [(job_id, "handler failed", None)])

    def test_concurrent_claims_select_distinct_rows(self):
        ids = {self.enqueue(), self.enqueue()}
        barrier = threading.Barrier(2)

        def parse(message):
            barrier.wait(timeout=3)
            return message.msg_data

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.prepare, parse=parse) for _ in range(2)]
            selected = [future.result(timeout=5)[0].msg_id for future in futures]
        self.assertEqual(set(selected), ids)
        with self.pool.connection() as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM cpkit.mq").fetchone()[0], 0
            )

    def test_actual_serialization_conflict_rolls_back_claim(self):
        job_id = self.enqueue()
        with self.pool.connection() as selected_conn:
            selected_conn.execute("SET default_transaction_isolation = 'serializable'")

            class BoundPool:
                @contextmanager
                def connection(self):
                    yield selected_conn

            def parse(message):
                selected_conn.execute(
                    "SELECT value FROM cpkit.worker_serialization_test WHERE id=1"
                ).fetchone()
                with psycopg.connect(DB_URL) as other:
                    other.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    other.execute(
                        "SELECT * FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                    ).fetchone()
                    other.execute(
                        "UPDATE cpkit.worker_serialization_test SET value=value+1 WHERE id=1"
                    )
                return message.msg_data

            try:
                # PostgreSQL may detect the serialization cycle at DELETE or COMMIT.
                with self.assertRaises(
                    (psycopg.errors.SerializationFailure, QueueDispatchError)
                ) as caught:
                    self.prepare(pool=BoundPool(), parse=parse)
                if isinstance(caught.exception, QueueDispatchError):
                    self.assertEqual(caught.exception.phase, "commit_rejected")
                self.assertIsNotNone(
                    selected_conn.execute(
                        "SELECT 1 FROM cpkit.mq WHERE msg_id=%s", (job_id,)
                    ).fetchone()
                )
            finally:
                selected_conn.execute(
                    "SET default_transaction_isolation = 'read committed'"
                )
