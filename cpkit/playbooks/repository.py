"""Repository mixin for framework-owned versioned playbooks."""

from cpkit.db import execute_stmt, fetch_all, fetch_one

from .types import Playbook, PlaybookOverview

PLAYBOOKS_TABLE = "cpkit.playbooks"


class PlaybooksRepositoryMixin:
    def get_playbook(self, name: str, version: str) -> Playbook:
        return fetch_one(
            f"""
            SELECT *
            FROM {PLAYBOOKS_TABLE}
            WHERE (name, version) = (%s, %s)
            """,
            (name, version),
            Playbook,
        )

    def get_default_playbook(self, name: str) -> Playbook:
        return fetch_one(
            f"""
            SELECT *
            FROM {PLAYBOOKS_TABLE}
            WHERE name = %s
            ORDER BY default_version DESC NULLS LAST, version DESC
            LIMIT 1
            """,
            (name,),
            Playbook,
        )

    def list_playbook_versions(self, name: str) -> list[PlaybookOverview]:
        return fetch_all(
            f"""
            SELECT name, version, default_version, created_at, created_by, updated_by
            FROM {PLAYBOOKS_TABLE}
            WHERE name = %s
            ORDER BY version DESC;
            """,
            (name,),
            PlaybookOverview,
        )

    def create_playbook(
        self,
        name: str,
        content: bytes,
        created_by: str,
    ) -> PlaybookOverview:
        return fetch_one(
            f"""
            INSERT INTO {PLAYBOOKS_TABLE} (name, content, created_by)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (name, content, created_by),
            PlaybookOverview,
        )

    def set_default_playbook(self, name: str, version: str, updated_by: str) -> None:
        execute_stmt(
            f"""
            UPDATE {PLAYBOOKS_TABLE}
            SET
                default_version = now(),
                updated_by = %s
            WHERE (name, version) = (%s, %s)
            """,
            (updated_by, name, version),
        )

    def delete_playbook(self, name: str, version: str) -> None:
        execute_stmt(
            f"""
            DELETE
            FROM {PLAYBOOKS_TABLE}
            WHERE (name, version) = (%s, %s)
            """,
            (name, version),
        )
