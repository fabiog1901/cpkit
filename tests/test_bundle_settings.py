import unittest
from types import SimpleNamespace

from cpkit.bundle import _setting_updated_hook
from cpkit.playbooks import configure_playbook_run_options, get_playbook_run_options

DEFAULT_PLAYBOOK_SETTINGS = {
    "playbooks.ssh_credential_hook.enabled": "false",
    "playbooks.ssh_credential_hook.prepare_playbook": "SSH_CREDENTIAL_PREPARE",
    "playbooks.ssh_credential_hook.cleanup_playbook": "SSH_CREDENTIAL_CLEANUP",
    "playbooks.ssh_credential_hook.dir_root": "/tmp/cpkit/jobs",
    "playbooks.ssh_credential_hook.retain_artifacts_on_failure": "false",
}


class FakeSettingsRepo:
    def __init__(self, values):
        self.values = {**DEFAULT_PLAYBOOK_SETTINGS, **values}

    def get_setting(self, key):
        return SimpleNamespace(value=self.values[str(key)])


class BundleSettingsHookTests(unittest.TestCase):
    def tearDown(self):
        configure_playbook_run_options()

    def test_playbook_settings_update_refreshes_options_and_preserves_audit(self):
        audit_events = []
        repo = FakeSettingsRepo(
            {
                "playbooks.ssh_credential_hook.enabled": "true",
                "playbooks.ssh_credential_hook.dir_root": "/tmp/hook-refresh",
            }
        )

        hook = _setting_updated_hook(
            lambda repo, actor, action, details: audit_events.append(
                (actor, action, details)
            )
        )
        hook(
            repo,
            "playbooks.ssh_credential_hook.enabled",
            "true",
            "admin",
        )

        options = get_playbook_run_options()
        self.assertTrue(options.ssh_credential_hook_enabled)
        self.assertEqual(options.ssh_credential_dir_root, "/tmp/hook-refresh")
        self.assertEqual(
            audit_events,
            [
                (
                    "admin",
                    "SETTING_UPDATED",
                    {"ID": "playbooks.ssh_credential_hook.enabled", "value": "true"},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
