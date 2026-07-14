import unittest

from cpkit.bundle import _setting_updated_hook


class BundleSettingsHookTests(unittest.TestCase):
    def test_setting_update_preserves_audit(self):
        audit_events = []
        repo = object()

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
