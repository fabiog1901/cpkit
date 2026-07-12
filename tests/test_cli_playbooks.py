import gzip
import io
import datetime as dt
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cpkit.cli.base import ApplicationCLI
from cpkit.cli.schema import _initialize_playbooks_from_dirs, _iter_playbook_files
from cpkit.playbooks.types import Playbook


class FakePlaybookRepo:
    def __init__(self):
        self.rows = {}
        self.default_versions = {}
        self.counter = 0

    def get_default_playbook(self, name):
        version = self.default_versions.get(name)
        if version is None and self.rows:
            candidates = [
                row
                for (row_name, _version), row in self.rows.items()
                if row_name == name
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda row: row.version)
        if version is None:
            return None
        return self.rows[(name, version)]

    def create_playbook(self, name, content, created_by):
        self.counter += 1
        version = dt.datetime(2026, 7, 1, 12, 0, self.counter, tzinfo=dt.timezone.utc)
        playbook = Playbook(
            name=name,
            version=version,
            default_version=None,
            created_at=version,
            created_by=created_by,
            updated_by=None,
            content=content,
        )
        self.rows[(name, version.strftime("%Y-%m-%d %H:%M:%S"))] = playbook
        return playbook

    def set_default_playbook(self, name, version, updated_by):
        self.default_versions[name] = version
        row = self.rows[(name, version)]
        row.default_version = row.version
        row.updated_by = updated_by

    def delete_playbook(self, name, version):
        self.rows.pop((name, version), None)
        if self.default_versions.get(name) == version:
            self.default_versions.pop(name)


class PlaybookInitializationTests(unittest.TestCase):
    def test_playbooks_are_inserted_from_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "SERVER_INIT.yml").write_text(
                "---\n- hosts: all\n", encoding="utf-8"
            )
            repo = FakePlaybookRepo()

            _initialize_playbooks_from_dirs((root,), repo)

            self.assertEqual(
                repo.default_versions["SERVER_INIT"], "2026-07-01 12:00:01"
            )
            row = repo.rows[("SERVER_INIT", "2026-07-01 12:00:01")]
            self.assertEqual(
                gzip.decompress(row.content).decode("utf-8"), "---\n- hosts: all\n"
            )
            self.assertEqual(row.created_by, "system")
            self.assertEqual(row.updated_by, "system")

    def test_hidden_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".hidden.yml").write_text("hidden", encoding="utf-8")
            repo = FakePlaybookRepo()

            _initialize_playbooks_from_dirs((root,), repo)

            self.assertEqual(repo.rows, {})

    def test_unsupported_extensions_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("nope", encoding="utf-8")
            (root / "playbook.txt").write_text("nope", encoding="utf-8")

            self.assertEqual(_iter_playbook_files((root,)), [])

    def test_re_running_init_with_unchanged_files_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SERVER_INIT.yaml").write_text("same", encoding="utf-8")
            repo = FakePlaybookRepo()

            _initialize_playbooks_from_dirs((root,), repo)
            _initialize_playbooks_from_dirs((root,), repo)

            self.assertEqual(len(repo.rows), 1)
            self.assertEqual(
                repo.default_versions["SERVER_INIT"], "2026-07-01 12:00:01"
            )

    def test_existing_version_without_default_creates_default_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SERVER_INIT.yaml").write_text("same", encoding="utf-8")
            repo = FakePlaybookRepo()
            repo.create_playbook(
                "SERVER_INIT", gzip.compress(b"same"), created_by="system"
            )

            _initialize_playbooks_from_dirs((root,), repo)

            self.assertEqual(len(repo.rows), 1)
            self.assertEqual(
                repo.default_versions["SERVER_INIT"], "2026-07-01 12:00:01"
            )

    def test_changing_content_creates_new_default_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "SERVER_INIT.json"
            path.write_text('{"version": 1}', encoding="utf-8")
            repo = FakePlaybookRepo()

            _initialize_playbooks_from_dirs((root,), repo)
            path.write_text('{"version": 2}', encoding="utf-8")
            _initialize_playbooks_from_dirs((root,), repo)

            self.assertEqual(len(repo.rows), 1)
            self.assertEqual(
                repo.default_versions["SERVER_INIT"], "2026-07-01 12:00:02"
            )
            content = repo.rows[("SERVER_INIT", "2026-07-01 12:00:02")].content
            self.assertEqual(gzip.decompress(content).decode("utf-8"), '{"version": 2}')

    def test_from_project_reads_playbook_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "pyproject.toml").write_text(
                """
[project]
name = "sample"

[tool.cpkit]
app_import = "sample.main:app"
playbooks = [
    "sample/resources/playbooks",
]
""",
                encoding="utf-8",
            )

            cli = ApplicationCLI.from_project(project_root=root)

            self.assertEqual(
                cli.app_playbook_dirs,
                (root / "sample" / "resources" / "playbooks",),
            )

    def test_from_project_reads_playbook_dirs_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "pyproject.toml").write_text(
                """
[project]
name = "sample"
""",
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {"CPKIT_APP_PLAYBOOKS": "first/playbooks,second/playbooks"},
            ):
                cli = ApplicationCLI.from_project(project_root=root)

            self.assertEqual(
                cli.app_playbook_dirs,
                (
                    root / "first" / "playbooks",
                    root / "second" / "playbooks",
                ),
            )

    def test_init_applies_schema_then_playbooks_then_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_ddl = root / "ddl.sql"
            playbooks = root / "playbooks"
            app_ddl.write_text("SELECT 1;", encoding="utf-8")
            playbooks.mkdir()
            calls = []

            def fake_apply(_db_url, path):
                calls.append(("apply", Path(path).name))

            def fake_initialize(_db_url, dirs):
                calls.append(("playbooks", tuple(Path(path).name for path in dirs)))

            def fake_check_database(_db_url):
                calls.append(("check_database",))

            def fake_check_table(_db_url, table_name):
                calls.append(("check_table", table_name))

            cli = ApplicationCLI(
                app_name="sample",
                app_import="sample.main:app",
                app_ddl_paths=(app_ddl,),
                app_playbook_dirs=(playbooks,),
            )

            with (
                patch.dict("os.environ", {"CPKIT_DB_URL": "postgres://example"}),
                patch("cpkit.cli.base.apply_sql_file", fake_apply),
                patch("cpkit.cli.base.initialize_playbooks", fake_initialize),
                patch("cpkit.cli.base.check_database", fake_check_database),
                patch("cpkit.cli.base.check_table", fake_check_table),
            ):
                with redirect_stdout(io.StringIO()):
                    cli.init(object())

            self.assertEqual(
                calls,
                [
                    ("apply", "ddl.sql"),
                    ("apply", "ddl.sql"),
                    ("playbooks", ("playbooks",)),
                    ("check_database",),
                    ("check_table", "cpkit.settings"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
