"""Repository mixin for a key/value settings table."""

from typing import Any

from cpkit.db import fetch_all, fetch_one

from .types import SettingRecord

SETTINGS_TABLE = "cpkit.settings"


class SettingsRepositoryMixin:
    def list_settings(self) -> list[SettingRecord]:
        return fetch_all(
            f"""
            SELECT
                key,
                COALESCE(value, default_value) AS value,
                default_value,
                value_type,
                category,
                is_secret,
                description,
                updated_at,
                updated_by
            FROM {SETTINGS_TABLE}
            ORDER BY category, key
            """,
            (),
            SettingRecord,
        )

    def get_setting(self, key: Any) -> SettingRecord | None:
        return fetch_one(
            f"""
            SELECT
                key,
                COALESCE(value, default_value) AS value,
                default_value,
                value_type,
                category,
                is_secret,
                description,
                updated_at,
                updated_by
            FROM {SETTINGS_TABLE}
            WHERE key = %s
            """,
            (key,),
            SettingRecord,
        )

    def update_setting(
        self,
        key: Any,
        value,
        updated_by: str | None = None,
    ) -> SettingRecord | None:
        return fetch_one(
            f"""
            UPDATE {SETTINGS_TABLE}
            SET
                value = %s,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s
            WHERE key = %s
            RETURNING
                key,
                value,
                default_value,
                value_type,
                category,
                is_secret,
                description,
                updated_at,
                updated_by
            """,
            (value, updated_by, key),
            SettingRecord,
        )

    def reset_setting(
        self,
        key: Any,
        updated_by: str | None = None,
    ) -> SettingRecord | None:
        return fetch_one(
            f"""
            UPDATE {SETTINGS_TABLE}
            SET
                value = NULL,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s
            WHERE key = %s
            RETURNING
                key,
                value,
                default_value,
                value_type,
                category,
                is_secret,
                description,
                updated_at,
                updated_by
            """,
            (updated_by, key),
            SettingRecord,
        )
