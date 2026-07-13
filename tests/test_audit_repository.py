import unittest
from unittest.mock import patch

from cpkit.audit.repository import AuditEventsRepositoryMixin


class AuditEventsRepositoryTests(unittest.TestCase):
    def test_event_count_query_is_postgres_compatible(self):
        repo = AuditEventsRepositoryMixin()

        with patch("cpkit.audit.repository.fetch_scalar", return_value=3) as fetch:
            self.assertEqual(repo.get_event_count(), 3)

        sql = fetch.call_args.args[0]
        self.assertIn("FROM cpkit.event_log", sql)
        self.assertNotIn("AS OF SYSTEM TIME", sql)
        self.assertNotIn("follower_read_timestamp", sql)


if __name__ == "__main__":
    unittest.main()
