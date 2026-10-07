import os
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import class_row

from cpkit.db import (
    close_db,
    fetch_scalar,
    initialize_postgres,
    transaction,
)
from cpkit.errors import RepositoryValidationError
from cpkit.jobs.repository import QueueJobRepositoryMixin
from cpkit.jobs.types import QueueMessage
from cpkit.jobs.worker import _claim_due_message

INTEGRATION_DB_URL = os.getenv("CPKIT_INTEGRATION_DB_URL")


class IntegrationQueueRepo(QueueJobRepositoryMixin):
    pass


@unittest.skipUnless(
    INTEGRATION_DB_URL,
    "CPKIT_INTEGRATION_DB_URL is required for database integration tests",
)
class TransactionalEnqueueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert INTEGRATION_DB_URL is not None
        schema = (
            Path(__file__).parents[1] / "cpkit" / "resources" / "ddl.sql"
        ).read_text()
        with psycopg.connect(INTEGRATION_DB_URL, autocommit=True) as conn:
            cls.database_version = conn.execute("SELECT version()").fetchone()[0]
            conn.execute(schema)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cpkit.transaction_test_state (
                    request_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL
                )
                """)
        initialize_postgres(INTEGRATION_DB_URL)

    @classmethod
    def tearDownClass(cls):
        close_db()

    def setUp(self):
        self.repo = IntegrationQueueRepo()
        self.request_id = f"transaction-test-{uuid4()}"

    def tearDown(self):
        assert INTEGRATION_DB_URL is not None
        with psycopg.connect(INTEGRATION_DB_URL, autocommit=True) as conn:
            conn.execute(
                "DELETE FROM cpkit.mq WHERE created_by = %s",
                (self.request_id,),
            )
            conn.execute(
                "DELETE FROM cpkit.jobs WHERE created_by = %s",
                (self.request_id,),
            )
            conn.execute(
                "DELETE FROM cpkit.transaction_test_state WHERE request_id = %s",
                (self.request_id,),
            )

    def test_commit_persists_business_message_and_job_rows(self):
        with transaction(operation="test.transactional_enqueue") as tx:
            tx.execute_stmt(
                """
                INSERT INTO cpkit.transaction_test_state (request_id, state)
                VALUES (%s, %s)
                """,
                (self.request_id, "PENDING"),
            )
            job = self.repo.enqueue_command(
                "TEST_TRANSACTIONAL_ENQUEUE",
                {"request_id": self.request_id, "playbook_version": 3},
                self.request_id,
                tx=tx,
            )

        self.assertEqual(
            fetch_scalar(
                "SELECT count(*) FROM cpkit.transaction_test_state WHERE request_id = %s",
                (self.request_id,),
            ),
            1,
        )
        self.assertEqual(
            fetch_scalar(
                "SELECT count(*) FROM cpkit.mq WHERE msg_id = %s AND created_by = %s",
                (job.job_id, self.request_id),
            ),
            1,
        )
        self.assertEqual(
            fetch_scalar(
                """
                SELECT count(*) FROM cpkit.jobs
                WHERE job_id = %s
                    AND job_type = %s
                    AND status = %s
                    AND playbook_version = %s
                    AND description = %s
                    AND created_by = %s
                """,
                (
                    job.job_id,
                    "TEST_TRANSACTIONAL_ENQUEUE",
                    "QUEUED",
                    "3",
                    {"request_id": self.request_id},
                    self.request_id,
                ),
            ),
            1,
        )

    def test_later_failure_rolls_back_business_message_and_job_rows(self):
        with self.assertRaisesRegex(RuntimeError, "later write failed"):
            with transaction(operation="test.transactional_enqueue") as tx:
                tx.execute_stmt(
                    """
                    INSERT INTO cpkit.transaction_test_state (request_id, state)
                    VALUES (%s, %s)
                    """,
                    (self.request_id, "PENDING"),
                )
                self.repo.enqueue_command(
                    "TEST_TRANSACTIONAL_ENQUEUE",
                    {"request_id": self.request_id},
                    self.request_id,
                    tx=tx,
                )
                raise RuntimeError("later write failed")

        self._assert_no_rows()

    def test_enqueue_failure_rolls_back_earlier_business_write(self):
        with self.assertRaises(RepositoryValidationError):
            with transaction(operation="test.transactional_enqueue") as tx:
                tx.execute_stmt(
                    """
                    INSERT INTO cpkit.transaction_test_state (request_id, state)
                    VALUES (%s, %s)
                    """,
                    (self.request_id, "PENDING"),
                )
                self.repo.enqueue_command(
                    "TEST_TRANSACTIONAL_ENQUEUE",
                    {"request_id": self.request_id},
                    None,
                    tx=tx,
                )

        self._assert_no_rows()

    def test_rows_are_hidden_until_commit_then_message_can_be_claimed(self):
        assert INTEGRATION_DB_URL is not None
        if "CockroachDB" in self.database_version:
            self.skipTest(
                "CockroachDB waits on the uncommitted range intent instead of "
                "using PostgreSQL's tuple visibility behavior"
            )
        with transaction(operation="test.transactional_enqueue") as tx:
            tx.execute_stmt(
                """
                INSERT INTO cpkit.transaction_test_state (request_id, state)
                VALUES (%s, %s)
                """,
                (self.request_id, "PENDING"),
            )
            job = self.repo.enqueue_command(
                "TEST_TRANSACTIONAL_ENQUEUE",
                {"request_id": self.request_id},
                self.request_id,
                tx=tx,
            )

            with psycopg.connect(INTEGRATION_DB_URL) as other_conn:
                with other_conn.cursor(row_factory=class_row(QueueMessage)) as cur:
                    self.assertIsNone(_claim_due_message(cur))
                self.assertEqual(
                    other_conn.execute(
                        """
                        SELECT count(*) FROM cpkit.transaction_test_state
                        WHERE request_id = %s
                        """,
                        (self.request_id,),
                    ).fetchone()[0],
                    0,
                )

        with psycopg.connect(INTEGRATION_DB_URL) as other_conn:
            with other_conn.cursor(row_factory=class_row(QueueMessage)) as cur:
                claimed = _claim_due_message(cur)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.msg_id, job.job_id)

    def _assert_no_rows(self):
        self.assertEqual(
            fetch_scalar(
                "SELECT count(*) FROM cpkit.transaction_test_state WHERE request_id = %s",
                (self.request_id,),
            ),
            0,
        )
        self.assertEqual(
            fetch_scalar(
                "SELECT count(*) FROM cpkit.mq WHERE created_by = %s",
                (self.request_id,),
            ),
            0,
        )
        self.assertEqual(
            fetch_scalar(
                "SELECT count(*) FROM cpkit.jobs WHERE created_by = %s",
                (self.request_id,),
            ),
            0,
        )
