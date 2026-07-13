import unittest

from cpkit.auth.config import OIDCConfig
from cpkit.auth.dependencies import create_auth_dependencies
from cpkit.auth.oidc import OIDCManager


class AuthDependenciesTests(unittest.TestCase):
    def test_auth_disabled_claims_are_admin_scoped(self):
        oidc = OIDCManager(
            config=OIDCConfig(),
            encrypt_secret=lambda value: b"",
            decrypt_secret=lambda value: b"",
            session_record_factory=lambda **kwargs: kwargs,
        )
        dependencies = create_auth_dependencies(
            oidc,
            get_repo=lambda: None,
            readonly_roles=("CP_READONLY",),
            user_roles=("CP_USER",),
            admin_roles=("CP_ADMIN",),
        )

        self.assertEqual(
            dependencies.get_access_scope(
                {
                    "sub": "anonymous",
                    "auth_disabled": True,
                }
            ),
            ([], True),
        )


if __name__ == "__main__":
    unittest.main()
