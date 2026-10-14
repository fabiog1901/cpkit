import os
import base64
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path

import psycopg
from fastapi import APIRouter
from cpkit.auth.api_key_service import ApiKeysService
from cpkit.auth.repositories import APIKeysRepositoryMixin
from cpkit.auth.types import ApiKeyCreateRequest
from cpkit.bundle import create_cpkit_bundle
from cpkit.db import close_db, initialize_postgres, transaction


class ApiKeyCompositionTests(unittest.TestCase):
    def test_bound_repository_and_delete_lock_do_not_open_independent_helpers(self):
        repo, tx = APIKeysRepositoryMixin(), MagicMock()
        with (
            patch(
                "cpkit.auth.repositories.fetch_one",
                side_effect=AssertionError("independent read"),
            ),
            patch(
                "cpkit.auth.repositories.execute_stmt",
                side_effect=AssertionError("independent write"),
            ),
        ):
            repo.get_api_key("key", tx=tx, for_update=True)
            self.assertIn("FOR UPDATE", tx.fetch_one.call_args.args[0])
            repo.create_api_key(
                SimpleNamespace(
                    access_key="key", valid_until=datetime.now(timezone.utc), roles=[]
                ),
                owner="actor",
                encrypted_secret_access_key=b"encrypted",
                tx=tx,
            )
            repo.delete_api_key("key", tx=tx)
        self.assertEqual(tx.fetch_one.call_count, 2)
        tx.execute_stmt.assert_called_once()
        with self.assertRaises(ValueError):
            repo.get_api_key("key", for_update=True)

    def test_service_composition_uses_bound_helpers_and_leaves_audit_to_outer_owner(
        self,
    ):
        repo, tx, created, deleted = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        expires = datetime.now(timezone.utc) + timedelta(days=1)
        repo.create_api_key.return_value = SimpleNamespace(
            access_key="key", owner="actor", valid_until=expires, roles=["CP_USER"]
        )
        repo.get_api_key.return_value = repo.create_api_key.return_value
        service = ApiKeysService(repo, created_hook=created, deleted_hook=deleted)
        with patch(
            "cpkit.auth.api_key_service.encrypt_secret", return_value=b"encrypted"
        ):
            result = service.create_api_key(
                "actor",
                ApiKeyCreateRequest(valid_until=expires, roles=["CP_USER"]),
                tx=tx,
            )
        self.assertIs(repo.create_api_key.call_args.kwargs["tx"], tx)
        self.assertTrue(result.secret_access_key)
        service.delete_api_key("actor", "key", tx=tx)
        repo.get_api_key.assert_called_with("key", tx=tx, for_update=True)
        repo.delete_api_key.assert_called_with("key", tx=tx)
        created.assert_not_called()
        deleted.assert_not_called()

    def test_custom_router_replaces_default_and_retains_administrator_guard(self):
        custom = APIRouter(prefix="/api_keys")

        @custom.get("/")
        def custom_list():
            return []

        bundle = create_cpkit_bundle(
            api_keys_router=custom, parse_job_payload=lambda kind, payload: payload
        )
        routes = [
            r
            for group in bundle.routers
            for r in group.routes
            if r.path.startswith("/admin/api_keys")
        ]
        self.assertEqual(len(routes), 1)
        self.assertIs(routes[0].endpoint, custom_list)
        self.assertIn(
            bundle.auth.require_admin,
            {d.call for d in routes[0].dependant.dependencies},
        )
        default = create_cpkit_bundle(parse_job_payload=lambda kind, payload: payload)
        self.assertEqual(
            len(
                [
                    r
                    for group in default.routers
                    for r in group.routes
                    if r.path.startswith("/admin/api_keys")
                ]
            ),
            3,
        )


@unittest.skipUnless(
    os.getenv("CPKIT_INTEGRATION_DB_URL"), "CPKIT_INTEGRATION_DB_URL required"
)
class ApiKeyCompositionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ["CPKIT_INTEGRATION_DB_URL"]
        initialize_postgres(cls.url)
        cls.addClassCleanup(close_db)
        with psycopg.connect(cls.url, autocommit=True) as conn:
            conn.execute(
                (Path(__file__).parents[1] / "cpkit/resources/ddl.sql").read_text()
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cpkit.api_key_composition_test (access_key TEXT PRIMARY KEY)"
            )

    def setUp(self):
        patcher = patch.dict(
            os.environ, {"CPKIT_MASTER_KEY": base64.b64encode(os.urandom(32)).decode()}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = APIKeysRepositoryMixin()
        self.service = ApiKeysService(self.repo)
        self.request = ApiKeyCreateRequest(
            valid_until=datetime.now(timezone.utc) + timedelta(days=1),
            roles=["CP_USER"],
        )

    def test_create_rollback_and_commit_include_related_write(self):
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction() as tx:
                failed = self.service.create_api_key("test", self.request, tx=tx)
                tx.execute_stmt(
                    "INSERT INTO cpkit.api_key_composition_test VALUES (%s)",
                    (failed.access_key,),
                )
                raise RuntimeError("rollback")
        self.assertIsNone(self.repo.get_api_key(failed.access_key))
        with psycopg.connect(self.url) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM cpkit.api_key_composition_test WHERE access_key=%s",
                    (failed.access_key,),
                ).fetchone()[0],
                0,
            )
        with transaction() as tx:
            created = self.service.create_api_key("test", self.request, tx=tx)
            tx.execute_stmt(
                "INSERT INTO cpkit.api_key_composition_test VALUES (%s)",
                (created.access_key,),
            )
        self.addCleanup(self.service.delete_api_key, "test", created.access_key)
        self.assertIsNotNone(self.repo.get_api_key(created.access_key))

    def test_delete_and_related_retirement_rollback_and_commit_together(self):
        created = self.service.create_api_key("test", self.request)
        with transaction() as tx:
            tx.execute_stmt(
                "INSERT INTO cpkit.api_key_composition_test VALUES (%s)",
                (created.access_key,),
            )
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction() as tx:
                self.service.delete_api_key("test", created.access_key, tx=tx)
                tx.execute_stmt(
                    "DELETE FROM cpkit.api_key_composition_test WHERE access_key=%s",
                    (created.access_key,),
                )
                raise RuntimeError("rollback")
        self.assertIsNotNone(self.repo.get_api_key(created.access_key))
        with transaction() as tx:
            self.service.delete_api_key("test", created.access_key, tx=tx)
            tx.execute_stmt(
                "DELETE FROM cpkit.api_key_composition_test WHERE access_key=%s",
                (created.access_key,),
            )
        self.assertIsNone(self.repo.get_api_key(created.access_key))
