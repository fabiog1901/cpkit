"""Framework-owned job queue primitives."""

from .maintenance import FAIL_ZOMBIE_JOBS_MESSAGE_TYPE, create_fail_zombie_jobs_handler
from .recurring import (
    DEFAULT_RECURRING_MESSAGES,
    FAIL_ZOMBIE_JOBS_RECURRING_MESSAGE,
    configure_recurring_messages,
    get_recurring_messages,
)
from .repository import (
    JOBS_TABLE,
    QUEUE_TABLE,
    TASKS_TABLE,
    JobsRepositoryMixin,
    QueueJobRepositoryMixin,
    QueueRepositoryMixin,
)
from .router import create_jobs_router
from .service import JobsService
from .types import (
    IntID,
    Job,
    JobDetailsResponse,
    JobID,
    JobRescheduleResponse,
    JobStatsResponse,
    LinkedResourceRef,
    QueueMessage,
    RecurringMessage,
    Task,
)
from .worker import create_queue_worker, run_queue_worker

__all__ = [
    "FAIL_ZOMBIE_JOBS_MESSAGE_TYPE",
    "FAIL_ZOMBIE_JOBS_RECURRING_MESSAGE",
    "DEFAULT_RECURRING_MESSAGES",
    "IntID",
    "JOBS_TABLE",
    "Job",
    "JobDetailsResponse",
    "JobID",
    "JobRescheduleResponse",
    "JobStatsResponse",
    "JobsRepositoryMixin",
    "JobsService",
    "LinkedResourceRef",
    "QUEUE_TABLE",
    "QueueMessage",
    "QueueJobRepositoryMixin",
    "QueueRepositoryMixin",
    "RecurringMessage",
    "TASKS_TABLE",
    "Task",
    "configure_recurring_messages",
    "create_fail_zombie_jobs_handler",
    "create_queue_worker",
    "create_jobs_router",
    "get_recurring_messages",
    "run_queue_worker",
]
