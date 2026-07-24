import unittest
from unittest.mock import patch

from cpkit.jobs.repository import QueueRepositoryMixin
from cpkit.jobs.types import RecurringMessage


class FakeQueueRepo(QueueRepositoryMixin):
    pass


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


if __name__ == "__main__":
    unittest.main()
