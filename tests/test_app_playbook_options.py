import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cpkit.app import create_cpkit_app
from cpkit.playbooks import (
    configure_playbook_run_options,
    get_playbook_run_options,
)


class FakeSettingsRepo:
    def __init__(self, values=None):
        self.values = values or {}

    def get_setting(self, key):
        value = self.values.get(str(key))
        if value is None:
            return None
        return SimpleNamespace(value=value)


class AppPlaybookOptionsTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        configure_playbook_run_options()

    async def test_create_cpkit_app_loads_playbook_run_options_from_settings(self):
        app = create_cpkit_app(
            title="test",
            version="1",
            repo_class=lambda pool: object(),
            db_url="postgres://example",
        )
        repo = FakeSettingsRepo(
            {
                "playbooks.ssh_credential_hook.enabled": "true",
                "playbooks.ssh_credential_hook.dir_root": "/tmp/settings-playbooks",
            }
        )

        with (
            patch("cpkit.app.initialize_postgres"),
            patch("cpkit.app.configure_repository"),
            patch("cpkit.app.get_configured_repo", return_value=repo),
            patch("cpkit.app.configure_logging"),
            patch("cpkit.app.close_db"),
        ):
            async with app.router.lifespan_context(app):
                options = get_playbook_run_options()

        self.assertTrue(options.ssh_credential_hook_enabled)
        self.assertEqual(options.ssh_credential_dir_root, "/tmp/settings-playbooks")


if __name__ == "__main__":
    unittest.main()
