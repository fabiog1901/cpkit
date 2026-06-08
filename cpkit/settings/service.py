"""Service helpers for settings management."""

from collections.abc import Callable
from typing import Any

from cpkit.errors import RepositoryError, ServiceValidationError, from_repository_error

from .types import SettingRecord


class SettingsServiceMixin:
    """Generic settings service behavior with optional audit hooks."""

    repo: Any

    def list_settings(self) -> list[SettingRecord]:
        try:
            return self.repo.list_settings()
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Settings are temporarily unavailable.",
                fallback_message="Unable to load settings.",
            ) from err

    def get_setting(self, setting_id: str) -> str:
        try:
            setting_record = self.repo.get_setting(setting_id)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Settings are temporarily unavailable.",
                fallback_message=f"Unable to load setting '{setting_id}'.",
            ) from err

        if setting_record is None:
            raise ServiceValidationError(
                f"Required setting '{setting_id}' is not configured.",
                title="Missing Configuration",
            )

        return setting_record.value

    def update_setting(self, setting_id: str, value: str, updated_by: str) -> None:
        try:
            self.repo.update_setting(setting_id, value, updated_by)
            self.after_setting_updated(setting_id, value, updated_by)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Settings could not be updated right now.",
                conflict_message=f"Setting '{setting_id}' could not be updated because of a conflicting change.",
                validation_message=f"Setting '{setting_id}' has an invalid value.",
                fallback_message=f"Unable to update setting '{setting_id}'.",
            ) from err

    def reset_setting(self, setting_id: str, updated_by: str) -> None:
        try:
            self.repo.reset_setting(setting_id, updated_by)
            self.after_setting_reset(setting_id, updated_by)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Settings could not be updated right now.",
                conflict_message=f"Setting '{setting_id}' could not be reset because of a conflicting change.",
                validation_message=f"Setting '{setting_id}' could not be reset.",
                fallback_message=f"Unable to reset setting '{setting_id}'.",
            ) from err

    def after_setting_updated(
        self,
        setting_id: str,
        value: str,
        updated_by: str,
    ) -> None:
        pass

    def after_setting_reset(self, setting_id: str, updated_by: str) -> None:
        pass


class SettingsService(SettingsServiceMixin):
    def __init__(
        self,
        repo,
        *,
        setting_updated_hook: Callable[[Any, str, str, str], None] | None = None,
        setting_reset_hook: Callable[[Any, str, str], None] | None = None,
    ) -> None:
        self.repo = repo
        self.setting_updated_hook = setting_updated_hook
        self.setting_reset_hook = setting_reset_hook

    def after_setting_updated(
        self,
        setting_id: str,
        value: str,
        updated_by: str,
    ) -> None:
        if self.setting_updated_hook is not None:
            self.setting_updated_hook(self.repo, setting_id, value, updated_by)

    def after_setting_reset(self, setting_id: str, updated_by: str) -> None:
        if self.setting_reset_hook is not None:
            self.setting_reset_hook(self.repo, setting_id, updated_by)
