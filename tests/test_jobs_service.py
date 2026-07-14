import datetime as dt
import unittest

from cpkit.jobs.service import JobsService
from cpkit.jobs.types import Job, JobID


class FakeJobsRepo:
    def __init__(self):
        self.enqueued = []
        self.job = Job(
            job_id=101,
            job_type="SERVER_INIT",
            status="FAILED",
            description={"cluster": "prod-a"},
            created_at=dt.datetime(2026, 7, 14, 12, 0, tzinfo=dt.timezone.utc),
            created_by="alice",
            updated_at=dt.datetime(2026, 7, 14, 12, 1, tzinfo=dt.timezone.utc),
        )

    def get_job(self, job_id, groups, is_admin):
        if job_id != self.job.job_id:
            return None
        return self.job

    def enqueue_command(self, command_type, payload, created_by):
        self.enqueued.append((command_type, payload, created_by))
        return JobID(job_id=202)


class JobsServiceTests(unittest.TestCase):
    def test_reschedule_audit_details_include_source_and_replacement_job_type(self):
        audit_events = []
        repo = FakeJobsRepo()
        service = JobsService(
            repo,
            parse_payload=lambda command_type, payload: {
                **payload,
                "reschedule_type": command_type,
            },
            reschedule_type_resolver=lambda job_type: f"{job_type}_RETRY",
            rescheduled_hook=lambda repo, actor, action, details: audit_events.append(
                (actor, action, details)
            ),
        )

        new_job_id = service.enqueue_job_reschedule(
            101,
            groups=[],
            is_admin=True,
            requested_by="bob",
        )

        self.assertEqual(new_job_id, 202)
        self.assertEqual(repo.enqueued[0][0], "SERVER_INIT_RETRY")
        self.assertEqual(
            audit_events,
            [
                (
                    "bob",
                    "JOB_RESCHEDULE_REQUESTED",
                    {
                        "cluster": "prod-a",
                        "reschedule_type": "SERVER_INIT_RETRY",
                        "job_id": 101,
                        "job_type": "SERVER_INIT",
                        "source_job_id": 101,
                        "source_job_type": "SERVER_INIT",
                        "replacement_job_id": 202,
                        "replacement_job_type": "SERVER_INIT_RETRY",
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
