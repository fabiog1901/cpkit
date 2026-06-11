"""Service helpers for versioned playbook management."""

import gzip
from collections.abc import Callable
from typing import Any

from cpkit.errors import (
    RepositoryError,
    ServiceNotFoundError,
    ServiceValidationError,
    from_repository_error,
)
from cpkit.time import STRFTIME

from .types import (
    Playbook,
    PlaybookListResponse,
    PlaybookOverview,
    PlaybookResponse,
    PlaybookVersionResponse,
)

PlaybookAuditHook = Callable[[Any, str, str, dict[str, Any]], None]


class PlaybooksService:
    def __init__(
        self,
        repo,
        *,
        version_created_hook: PlaybookAuditHook | None = None,
        version_deleted_hook: PlaybookAuditHook | None = None,
        default_set_hook: PlaybookAuditHook | None = None,
    ) -> None:
        self.repo = repo
        self.version_created_hook = version_created_hook
        self.version_deleted_hook = version_deleted_hook
        self.default_set_hook = default_set_hook

    def list_playbooks(self) -> PlaybookListResponse:
        try:
            names = self.repo.list_playbook_names()
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbooks are temporarily unavailable.",
                fallback_message="Unable to list playbooks.",
            ) from err
        return PlaybookListResponse(playbooks=names)

    def get_playbook(self, name: str) -> PlaybookResponse:
        try:
            versions = self.repo.list_playbook_versions(name)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbooks are temporarily unavailable.",
                fallback_message=f"Unable to load playbook '{name}'.",
            ) from err
        version_strings = sorted([x.version.strftime(STRFTIME) for x in versions])
        selected_version = self._find_default_version(versions)

        try:
            playbook = self.repo.get_playbook(name, selected_version)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbooks are temporarily unavailable.",
                fallback_message=f"Unable to load playbook '{name}'.",
            ) from err
        content = self._decode_playbook(playbook)

        return PlaybookResponse(
            name=name,
            version=selected_version,
            default_version=selected_version,
            available_versions=version_strings,
            original_content=content,
            modified_content=content,
        )

    def get_playbook_version(self, name: str, version: str) -> PlaybookVersionResponse:
        try:
            playbook = self.repo.get_playbook(name, version)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbooks are temporarily unavailable.",
                fallback_message=f"Unable to load playbook '{name}'.",
            ) from err
        content = self._decode_playbook(playbook)
        return PlaybookVersionResponse(
            playbook_version=version,
            original_content=content,
            modified_content=content,
        )

    def set_default_playbook(self, name: str, version: str, updated_by: str) -> None:
        try:
            self.repo.set_default_playbook(name, version, updated_by)
            if self.default_set_hook is not None:
                self.default_set_hook(
                    self.repo,
                    updated_by,
                    "PLAYBOOK_DEFAULT_SET",
                    {"name": name, "version": version},
                )
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbook updates are temporarily unavailable.",
                fallback_message=f"Unable to set default playbook version for '{name}'.",
            ) from err

    def delete_playbook_version(
        self,
        name: str,
        version: str,
        deleted_by: str,
    ) -> PlaybookVersionResponse:
        try:
            default_playbook = self.repo.get_default_playbook(name)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbook updates are temporarily unavailable.",
                fallback_message=f"Unable to delete playbook version for '{name}'.",
            ) from err

        default_version = default_playbook.version.strftime(STRFTIME)
        if version == default_version:
            raise ServiceValidationError("Cannot delete the default version.")

        try:
            self.repo.delete_playbook(name, version)
            if self.version_deleted_hook is not None:
                self.version_deleted_hook(
                    self.repo,
                    deleted_by,
                    "PLAYBOOK_VERSION_DELETED",
                    {"name": name, "version": version},
                )

            versions = self.repo.list_playbook_versions(name)
            selected_version = default_version
            playbook = self.repo.get_playbook(name, selected_version)
            content = self._decode_playbook(playbook)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbook updates are temporarily unavailable.",
                fallback_message=f"Unable to delete playbook version for '{name}'.",
            ) from err

        return PlaybookVersionResponse(
            available_versions=sorted([x.version.strftime(STRFTIME) for x in versions]),
            playbook_version=selected_version,
            default_version=default_version,
            original_content=content,
            modified_content=content,
        )

    def save_playbook(
        self, name: str, content: str, created_by: str
    ) -> PlaybookVersionResponse:
        try:
            saved = self.repo.create_playbook(
                name,
                gzip.compress(content.encode("utf-8")),
                created_by,
            )
            saved_version = saved.version.strftime(STRFTIME)
            if self.version_created_hook is not None:
                self.version_created_hook(
                    self.repo,
                    created_by,
                    "PLAYBOOK_VERSION_CREATED",
                    {"name": name, "version": saved_version},
                )

            versions = self.repo.list_playbook_versions(name)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Playbook saves are temporarily unavailable.",
                conflict_message=f"A conflicting playbook version already exists for '{name}'.",
                fallback_message=f"Unable to save playbook '{name}'.",
            ) from err
        return PlaybookVersionResponse(
            available_versions=sorted([x.version.strftime(STRFTIME) for x in versions]),
            playbook_version=saved_version,
            original_content=content,
            modified_content=content,
        )

    @staticmethod
    def _find_default_version(versions: list[PlaybookOverview]) -> str:
        selected_version = ""
        running_default = ""
        for item in versions:
            if (
                item.default_version
                and item.default_version.strftime(STRFTIME) > running_default
            ):
                running_default = item.default_version.strftime(STRFTIME)
                selected_version = item.version.strftime(STRFTIME)

        if selected_version:
            return selected_version
        if versions:
            return versions[-1].version.strftime(STRFTIME)
        raise ServiceNotFoundError("No playbook versions found.")

    @staticmethod
    def _decode_playbook(playbook: Playbook) -> str:
        if playbook.content is None:
            return ""
        return gzip.decompress(playbook.content).decode("utf-8")
