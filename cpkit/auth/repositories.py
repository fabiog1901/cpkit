"""Repository mixins for framework-owned auth tables."""

from cpkit.db import execute_stmt, fetch_all, fetch_one

from .types import ApiKeyRecord, ApiKeySummary, OIDCSessionRecord, RoleGroupMap

API_KEYS_TABLE = "cpkit.api_keys"
OIDC_SESSIONS_TABLE = "cpkit.oidc_sessions"
ROLE_GROUP_MAPPINGS_TABLE = "cpkit.role_to_groups_mappings"


class APIKeysRepositoryMixin:
    api_key_record_type = ApiKeyRecord
    api_key_summary_type = ApiKeySummary

    def get_api_key(self, access_key: str):
        return fetch_one(
            f"""
                    SELECT access_key, encrypted_secret_access_key, owner, valid_until, roles
                    FROM {API_KEYS_TABLE}
                    WHERE access_key = %s
                    """,
            (access_key,),
            self.api_key_record_type,
            operation="api_keys.get",
        )

    def list_api_keys(self, access_key: str | None = None):
        params: list[str] = []
        sql = f"""
            SELECT access_key, owner, valid_until, roles
            FROM {API_KEYS_TABLE}
        """

        if access_key is not None:
            sql += " WHERE access_key = %s"
            params.append(access_key)

        sql += " ORDER BY access_key"

        return fetch_all(
            sql,
            tuple(params),
            self.api_key_summary_type,
            operation="api_keys.list",
        )

    def create_api_key(
        self,
        api_key,
        *,
        owner: str,
        encrypted_secret_access_key: bytes,
    ):
        return fetch_one(
            f"""
                    INSERT INTO {API_KEYS_TABLE} (
                        access_key,
                        encrypted_secret_access_key,
                        owner,
                        valid_until,
                        roles
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING access_key, owner, valid_until, roles
                    """,
            (
                api_key.access_key,
                encrypted_secret_access_key,
                owner,
                api_key.valid_until,
                api_key.roles,
            ),
            self.api_key_summary_type,
            operation="api_keys.create",
        )

    def delete_api_key(self, access_key: str) -> None:
        execute_stmt(
            f"""
                DELETE
                FROM {API_KEYS_TABLE}
                WHERE access_key = %s
                """,
            (access_key,),
            operation="api_keys.delete",
        )


class OIDCSessionsRepositoryMixin:
    oidc_session_record_type = OIDCSessionRecord

    def get_oidc_session(self, session_id: str):
        return fetch_one(
            f"""
            SELECT
                session_id,
                encrypted_id_token,
                encrypted_refresh_token,
                token_expires_at,
                session_expires_at,
                created_at,
                updated_at
            FROM {OIDC_SESSIONS_TABLE}
            WHERE session_id = %s
                AND session_expires_at > now()
            """,
            (session_id,),
            self.oidc_session_record_type,
            operation="auth.get_oidc_session",
        )

    def create_oidc_session(self, session) -> None:
        execute_stmt(
            f"""
            INSERT INTO {OIDC_SESSIONS_TABLE}
                (session_id, encrypted_id_token, encrypted_refresh_token,
                 token_expires_at, session_expires_at)
            VALUES
                (%s, %s, %s, %s, %s)
            """,
            (
                session.session_id,
                session.encrypted_id_token,
                session.encrypted_refresh_token,
                session.token_expires_at,
                session.session_expires_at,
            ),
            operation="auth.create_oidc_session",
        )

    def update_oidc_session(
        self,
        session_id: str,
        *,
        encrypted_id_token: bytes,
        encrypted_refresh_token: bytes | None,
        token_expires_at,
    ) -> None:
        execute_stmt(
            f"""
            UPDATE {OIDC_SESSIONS_TABLE}
            SET
                encrypted_id_token = %s,
                encrypted_refresh_token = %s,
                token_expires_at = %s
            WHERE session_id = %s
            """,
            (
                encrypted_id_token,
                encrypted_refresh_token,
                token_expires_at,
                session_id,
            ),
            operation="auth.update_oidc_session",
        )

    def delete_oidc_session(self, session_id: str) -> None:
        execute_stmt(
            f"""
            DELETE FROM {OIDC_SESSIONS_TABLE}
            WHERE session_id = %s
            """,
            (session_id,),
            operation="auth.delete_oidc_session",
        )


class RoleGroupMappingsRepositoryMixin:
    role_group_map_type = RoleGroupMap

    def list_role_group_mappings(self) -> list[RoleGroupMap]:
        return fetch_all(
            f"""
            SELECT role, groups
            FROM {ROLE_GROUP_MAPPINGS_TABLE}
            """,
            (),
            self.role_group_map_type,
            operation="auth.list_role_group_mappings",
        )
