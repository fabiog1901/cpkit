# Jobs

The jobs package owns cpkit's framework job history and queue mechanics. A job
is represented by a row in `cpkit.jobs`; queued work is represented by a row in
`cpkit.mq`, where the queue message id doubles as the job id for normal app
jobs.

## Files

- `types.py`: Job, task, queue, stats, and detail response models.
- `recurring.py`: Built-in and configured recurring singleton messages.
- `repository.py`: Repository mixins for jobs, tasks, linked resources, and the
  queue table.
- `service.py`: Job listing, detail loading, stats, and rescheduling rules.
- `router.py`: Jobs API routes.
- `worker.py`: Background queue poller and handler dispatch.
- `maintenance.py`: Framework maintenance queue handlers, such as zombie job
  cleanup.

## Runtime Flow

1. App code enqueues work through the repository/service.
2. The queue worker claims due messages from `cpkit.mq`.
3. The worker resolves a handler and calls it with `(job_id, payload, created_by)`.
4. Handlers update `cpkit.jobs` and write task rows as work progresses.
5. The Jobs page reads job rows, task rows, and stats through the Jobs API.

When a normal queue message is being processed, the worker sets the current
audit job context so audit records can store the job id separately from details.

## Transactional Scheduling

Applications can make job scheduling atomic with their own database writes by
passing the `DatabaseTransaction` yielded by `cpkit.db.transaction()` to
`enqueue_command()`:

```python
from cpkit.db import transaction

with transaction(operation="host.decommission.request") as tx:
    tx.execute_stmt(
        "UPDATE hosts SET status = %s WHERE hostname = %s",
        ("DECOMMISSIONING", hostname),
    )
    job = repo.enqueue_command(
        QueueCommand.SERVER_DECOMM,
        request,
        actor_id,
        tx=tx,
    )

# The job is committed before it is returned as successfully scheduled.
return job
```

The application owns the transaction. `enqueue_command()` uses the supplied
transaction's bound query helper and does not acquire another connection,
commit, or roll back. Its returned job id is provisional until the surrounding
context commits. An exception from enqueue, a later business write, or commit
causes the normal transaction error and rollback behavior. Omitting `tx`
preserves standalone enqueue behavior.

The business tables and CPKit tables must be reachable through the same database
transaction. Keep remote work and worker execution outside this transaction.
Retryable serialization failures require retrying the complete business
operation in a fresh transaction; an uncertain commit result requires an
application reconciliation or idempotency policy before retrying. Transaction
objects are context-bound and must not be retained or passed to workers.

## Recurring Messages

Recurring messages are singleton rows in `cpkit.mq` marked with
`is_recurring = true`. Apps register them with `RecurringMessage` through
`create_cpkit_app(recurring_messages=...)`.

The worker handles recurring rows differently from one-shot jobs: when a
recurring row is due, the worker locks it, updates `start_after` to the next
future run, and only then dispatches the handler. The row is not deleted after
dispatch, and handlers should not reinsert or reschedule themselves.

cpkit registers `FAIL_ZOMBIE_JOBS` through the same recurring-message path.
That handler only marks stale `RUNNING` or `QUEUED` job rows as `FAILED`; the
worker owns the recurring schedule.

The default repository methods are application-agnostic and list framework job
records directly. Apps that need tenant, project, cluster, or other
domain-specific job visibility should override `get_job_stats()`, `list_jobs()`,
and `get_job()` in their own repository class.
