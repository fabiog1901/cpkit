import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from psycopg import OperationalError
from psycopg.errors import SerializationFailure

from cpkit.db import transaction
from cpkit.errors import RepositoryUnavailableError


@dataclass
class ExampleRow:
    value: int


def context_returning(value):
    context = MagicMock()
    context.__enter__.return_value = value
    context.__exit__.return_value = False
    return context


class PostgresTransactionTests(unittest.TestCase):
    def setUp(self):
        self.pool = MagicMock()
        self.conn = MagicMock()
        self.connection_context = context_returning(self.conn)
        self.transaction_context = context_returning(None)
        self.pool.connection.return_value = self.connection_context
        self.conn.transaction.return_value = self.transaction_context

    def test_transaction_helpers_share_one_connection(self):
        cursors = [MagicMock() for _ in range(4)]
        cursors[1].fetchall.return_value = [ExampleRow(1)]
        cursors[2].fetchone.return_value = ExampleRow(2)
        cursors[3].fetchone.return_value = (3,)
        self.conn.cursor.side_effect = [context_returning(cur) for cur in cursors]

        with (
            patch("cpkit.db.postgres.get_pool", return_value=self.pool),
            patch("cpkit.db.postgres._register_dumpers"),
        ):
            with transaction() as tx:
                tx.execute_stmt("UPDATE example\n SET value = %s", (1,))
                all_rows = tx.fetch_all("SELECT value FROM example", (), ExampleRow)
                one_row = tx.fetch_one("SELECT value FROM example", (), ExampleRow)
                scalar = tx.fetch_scalar("SELECT count(*) FROM example")

        self.pool.connection.assert_called_once_with()
        self.conn.transaction.assert_called_once_with()
        cursors[0].execute.assert_called_once_with(
            "UPDATE example SET value = %s", (1,)
        )
        self.assertEqual(all_rows, [ExampleRow(1)])
        self.assertEqual(one_row, ExampleRow(2))
        self.assertEqual(scalar, 3)
        self.transaction_context.__exit__.assert_called_once_with(None, None, None)

    def test_transaction_rolls_back_when_body_raises(self):
        with (
            patch("cpkit.db.postgres.get_pool", return_value=self.pool),
            patch("cpkit.db.postgres._register_dumpers"),
        ):
            with self.assertRaisesRegex(ValueError, "stop"):
                with transaction():
                    raise ValueError("stop")

        exit_args = self.transaction_context.__exit__.call_args.args
        self.assertIs(exit_args[0], ValueError)
        self.assertEqual(str(exit_args[1]), "stop")

    def test_transaction_translates_commit_failure(self):
        self.transaction_context.__exit__.side_effect = OperationalError("down")

        with (
            patch("cpkit.db.postgres.get_pool", return_value=self.pool),
            patch("cpkit.db.postgres._register_dumpers"),
            patch("cpkit.db.postgres.logger.exception"),
        ):
            with self.assertRaises(RepositoryUnavailableError) as raised:
                with transaction(operation="example.batch"):
                    pass

        self.assertEqual(raised.exception.operation, "example.batch")
        self.assertTrue(raised.exception.retryable)

    def test_transaction_preserves_retryable_serialization_failure(self):
        self.transaction_context.__exit__.side_effect = SerializationFailure(
            "restart transaction"
        )

        with (
            patch("cpkit.db.postgres.get_pool", return_value=self.pool),
            patch("cpkit.db.postgres._register_dumpers"),
            patch("cpkit.db.postgres.logger.exception"),
        ):
            with self.assertRaises(RepositoryUnavailableError) as raised:
                with transaction(operation="host.decommission.request"):
                    pass

        self.assertEqual(
            raised.exception.operation,
            "host.decommission.request",
        )
        self.assertTrue(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()
