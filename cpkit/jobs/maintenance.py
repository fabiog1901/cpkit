"""Framework job maintenance handlers."""

from collections.abc import Callable
from typing import Any

FAIL_ZOMBIE_JOBS_MESSAGE_TYPE = "FAIL_ZOMBIE_JOBS"


def create_fail_zombie_jobs_handler(get_repo: Callable[[], Any]):
    """Create a queue handler that marks stale framework jobs as failed."""

    def fail_zombie_jobs(_job_id: int, _command: Any, _requested_by: str) -> None:
        get_repo().fail_zombie_jobs()

    return fail_zombie_jobs
