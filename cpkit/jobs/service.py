"""Service helpers for framework job history and rescheduling."""

from collections.abc import Callable
from typing import Any

import yaml

from cpkit.errors import RepositoryError, ServiceNotFoundError, from_repository_error

from .types import Job, JobID, JobStatsResponse

PayloadParser = Callable[[Any, dict[str, Any]], Any]
RescheduleTypeResolver = Callable[[str], Any]
JobAuditHook = Callable[[Any, str, str, dict[str, Any]], None]


class JobsService:
    def __init__(
        self,
        repo,
        *,
        parse_payload: PayloadParser,
        reschedule_type_resolver: RescheduleTypeResolver,
        rescheduled_hook: JobAuditHook | None = None,
    ) -> None:
        self.repo = repo
        self.parse_payload = parse_payload
        self.reschedule_type_resolver = reschedule_type_resolver
        self.rescheduled_hook = rescheduled_hook

    def list_visible_jobs(self, groups: list[str], is_admin: bool) -> list[Job]:
        try:
            return self.repo.list_jobs(groups, is_admin)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Jobs are temporarily unavailable.",
                fallback_message="Unable to load jobs.",
            ) from err

    def get_visible_job_stats(
        self,
        groups: list[str],
        is_admin: bool,
    ) -> JobStatsResponse:
        try:
            return self.repo.get_job_stats(groups, is_admin)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Job stats are temporarily unavailable.",
                fallback_message="Unable to load job stats.",
            ) from err

    def get_job_for_user(
        self,
        job_id: int,
        groups: list[str],
        is_admin: bool,
    ) -> Job | None:
        try:
            return self.repo.get_job(job_id, groups, is_admin)
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Job details are temporarily unavailable.",
                fallback_message=f"Unable to load job '{job_id}'.",
            ) from err

    def get_job_details_for_user(
        self,
        job_id: int,
        groups: list[str],
        is_admin: bool,
    ) -> dict[str, Any] | None:
        selected_job = self.get_job_for_user(job_id, groups, is_admin)
        if selected_job is None:
            return None

        try:
            return {
                "job": selected_job,
                "description_yaml": yaml.dump(selected_job.description),
                "tasks": self.repo.list_tasks(job_id),
                "linked_resources": self.repo.list_linked_resources(job_id),
            }
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Job details are temporarily unavailable.",
                fallback_message=f"Unable to load tasks for job '{job_id}'.",
            ) from err

    def enqueue_job_reschedule(
        self,
        job_id: int,
        groups: list[str],
        is_admin: bool,
        requested_by: str,
    ) -> int:
        selected_job = self.get_job_for_user(job_id, groups, is_admin)
        if selected_job is None:
            raise ServiceNotFoundError(f"Job '{job_id}' was not found.")

        command_type = self.reschedule_type_resolver(selected_job.job_type)
        payload = self.parse_payload(command_type, selected_job.description)

        try:
            msg_id: JobID = self.repo.enqueue_command(
                command_type,
                payload,
                requested_by,
            )
            if self.rescheduled_hook is not None:
                self.rescheduled_hook(
                    self.repo,
                    requested_by,
                    "JOB_RESCHEDULE_REQUESTED",
                    _payload_value(payload) | {"job_id": msg_id.job_id},
                )
            return msg_id.job_id
        except RepositoryError as err:
            raise from_repository_error(
                err,
                unavailable_message="Job rescheduling is temporarily unavailable.",
                validation_message=(
                    "The job could not be rescheduled with its current payload."
                ),
                fallback_message=f"Unable to reschedule job '{job_id}'.",
            ) from err


def _payload_value(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {"payload": payload}
