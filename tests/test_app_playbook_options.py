import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cpkit.app import create_cpkit_app
from cpkit.jobs import (
    FAIL_ZOMBIE_JOBS_MESSAGE_TYPE,
    RecurringMessage,
    configure_recurring_messages,
)
from cpkit.playbooks import (
    configure_playbook_run_options,
    get_playbook_run_options,
)

DEFAULT_PLAYBOOK_SETTINGS = {
    "playbooks.ssh_credential_hook.enabled": "false",
    "playbooks.ssh_credential_hook.prepare_playbook": "SSH_CREDENTIAL_PREPARE",
    "playbooks.ssh_credential_hook.cleanup_playbook": "SSH_CREDENTIAL_CLEANUP",
    "playbooks.ssh_credential_hook.dir_root": "/tmp/cpkit/jobs",
    "playbooks.ssh_credential_hook.retain_artifacts_on_failure": "false",
}


class FakeSettingsRepo:
    def __init__(self, values=None):
        self.values = {**DEFAULT_PLAYBOOK_SETTINGS, **(values or {})}
        self.recurring_messages = None

    def get_setting(self, key):
        return SimpleNamespace(value=self.values[str(key)])

    def ensure_recurring_messages(self, messages):
        self.recurring_messages = messages


class AppPlaybookOptionsTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        configure_playbook_run_options()
        configure_recurring_messages()

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

    async def test_create_cpkit_app_ensures_builtin_and_app_recurring_messages(self):
        app = create_cpkit_app(
            title="test",
            version="1",
            repo_class=lambda pool: object(),
            db_url="postgres://example",
            recurring_messages=(
                RecurringMessage(
                    msg_type="SERVER_HEALTH_CHECK",
                    interval_seconds=300,
                    jitter_seconds=10,
                ),
            ),
        )
        repo = FakeSettingsRepo()

        with (
            patch("cpkit.app.initialize_postgres"),
            patch("cpkit.app.configure_repository"),
            patch("cpkit.app.get_configured_repo", return_value=repo),
            patch("cpkit.app.configure_logging"),
            patch("cpkit.app.close_db"),
        ):
            async with app.router.lifespan_context(app):
                messages = repo.recurring_messages

        self.assertIsNotNone(messages)
        self.assertEqual(
            [message.msg_type for message in messages],
            [FAIL_ZOMBIE_JOBS_MESSAGE_TYPE, "SERVER_HEALTH_CHECK"],
        )


if __name__ == "__main__":
    unittest.main()
