"""Service helpers for framework audit event reads."""

from cpkit.errors import RepositoryError, from_repository_error

from .types import AuditLogRecord


class AuditEventsService:
    def __init__(self, repo) -> None:
        self.repo = repo

    def list_visible_events(
        self,
        limit: int,
        offset: int,
        groups: list[str],
        is_admin: bool,
    ) -> list[AuditLogRecord]:
        try:
            return self.repo.list_events(limit, offset, groups, is_admin)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Events are temporarily unavailable.",
                fallback_message="Unable to load events.",
            ) from err

    def get_event_total(self) -> int:
        try:
            return self.repo.get_event_count()
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Event totals are temporarily unavailable.",
                fallback_message="Unable to load the event count.",
            ) from err
