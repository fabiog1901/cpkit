import unittest
from enum import Enum
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from cpkit.db import DatabaseTransaction
from cpkit.jobs.repository import QueueJobRepositoryMixin, QueueRepositoryMixin
from cpkit.jobs.types import JobID, RecurringMessage


class FakeQueueRepo(QueueRepositoryMixin):
    pass


class FakeQueueJobRepo(QueueJobRepositoryMixin):
    pass


class ExampleCommand(Enum):
    RUN_PLAYBOOK = "RUN_PLAYBOOK"


class ExamplePayload(BaseModel):
    hostname: str
    playbook_version: int


class QueueRepositoryTests(unittest.TestCase):
    def test_ensure_recurring_message_inserts_singleton_recurring_row(self):
        calls = []
        repo = FakeQueueRepo()
        message = RecurringMessage(
            msg_type="SERVER_HEALTH_CHECK",
            interval_seconds=300,
            jitter_seconds=10,
            payload={"scope": "all"},
            created_by="system",
        )

        with patch(
            "cpkit.jobs.repository.execute_stmt",
            lambda stmt, args, operation=None: calls.append((stmt, args, operation)),
        ):
            repo.ensure_recurring_message(message)

        self.assertEqual(len(calls), 1)
        stmt, args, operation = calls[0]
        self.assertIn("is_recurring", stmt)
        self.assertIn("WHERE NOT EXISTS", stmt)
        self.assertEqual(
            args,
            (
                "SERVER_HEALTH_CHECK",
                {"scope": "all"},
                "system",
                300,
                10,
                "SERVER_HEALTH_CHECK",
            ),
        )
        self.assertEqual(operation, "jobs.ensure_recurring_message")

    def test_ensure_recurring_messages_registers_each_message(self):
        calls = []
        repo = FakeQueueRepo()

        with patch.object(
            repo,
            "ensure_recurring_message",
            lambda message: calls.append(message.msg_type),
        ):
            repo.ensure_recurring_messages(
                (
                    RecurringMessage("FIRST", 60),
                    RecurringMessage("SECOND", 120),
                )
            )

        self.assertEqual(calls, ["FIRST", "SECOND"])


class QueueJobRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeQueueJobRepo()
        self.payload = ExamplePayload(hostname="host-1", playbook_version=7)
        self.expected_job_id = JobID(job_id=42)

    def assert_enqueue_call(self, query):
        query.assert_called_once()
        stmt, args, row_type = query.call_args.args
        self.assertIn("INSERT INTO cpkit.mq", stmt)
        self.assertIn("INSERT INTO cpkit.jobs", stmt)
        self.assertEqual(
            args,
            (
                "RUN_PLAYBOOK",
                {"hostname": "host-1", "playbook_version": 7},
                "operator",
                "RUN_PLAYBOOK",
                "QUEUED",
                "7",
                {"hostname": "host-1"},
                "operator",
            ),
        )
        self.assertIs(row_type, JobID)
        self.assertEqual(
            query.call_args.kwargs,
            {"operation": "jobs.enqueue_command"},
        )

    def test_enqueue_command_uses_standalone_helper_by_default(self):
        with patch(
            "cpkit.jobs.repository.fetch_one",
            return_value=self.expected_job_id,
        ) as fetch:
            result = self.repo.enqueue_command(
                ExampleCommand.RUN_PLAYBOOK,
                self.payload,
                "operator",
            )

        self.assertIs(result, self.expected_job_id)
        self.assert_enqueue_call(fetch)

    def test_enqueue_command_uses_supplied_transaction_helper(self):
        tx = MagicMock(spec=DatabaseTransaction)
        tx.fetch_one.return_value = self.expected_job_id

        with patch("cpkit.jobs.repository.fetch_one") as standalone_fetch:
            result = self.repo.enqueue_command(
                ExampleCommand.RUN_PLAYBOOK,
                self.payload,
                "operator",
                tx=tx,
            )

        self.assertIs(result, self.expected_job_id)
        standalone_fetch.assert_not_called()
        self.assert_enqueue_call(tx.fetch_one)

    def test_enqueue_command_does_not_fall_back_when_transaction_query_fails(self):
        tx = MagicMock(spec=DatabaseTransaction)
        tx.fetch_one.side_effect = RuntimeError("enqueue failed")

        with patch("cpkit.jobs.repository.fetch_one") as standalone_fetch:
            with self.assertRaisesRegex(RuntimeError, "enqueue failed"):
                self.repo.enqueue_command(
                    ExampleCommand.RUN_PLAYBOOK,
                    self.payload,
                    "operator",
                    tx=tx,
                )

        standalone_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
