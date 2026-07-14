import unittest
from unittest.mock import patch

from cpkit.app import create_cpkit_app
from cpkit.playbooks import (
    PlaybookRunOptions,
    configure_playbook_run_options,
    get_playbook_run_options,
)


class AppPlaybookOptionsTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        configure_playbook_run_options()

    async def test_create_cpkit_app_configures_playbook_run_options(self):
        options = PlaybookRunOptions(
            ssh_credential_hook_enabled=True,
            ssh_credential_dir_root="/tmp/app-playbooks",
        )
        app = create_cpkit_app(
            title="test",
            version="1",
            repo_class=lambda pool: object(),
            db_url="postgres://example",
            playbook_run_options=options,
        )

        with (
            patch("cpkit.app.initialize_postgres"),
            patch("cpkit.app.configure_repository"),
            patch("cpkit.app.get_configured_repo", return_value=object()),
            patch("cpkit.app.configure_logging"),
            patch("cpkit.app.close_db"),
        ):
            async with app.router.lifespan_context(app):
                self.assertEqual(get_playbook_run_options(), options)


if __name__ == "__main__":
    unittest.main()
