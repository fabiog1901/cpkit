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
3. The worker resolves a handler and parses the payload, then commits queue
   deletion or recurring rescheduling before submitting the handler with
   `(job_id, payload, created_by)`.
4. Handlers update `cpkit.jobs` and write task rows as work progresses.
5. The Jobs page reads job rows, task rows, and stats through the Jobs API.

When a normal queue message is being processed, the worker sets the current
audit job context so audit records can store the job id separately from details.

## Claim and Dispatch Failures

Each selection uses its own transaction on an idle pool connection. Handler
submission happens after the transaction commits and the connection is returned.
Handlers still run concurrently; the poller does not wait for handler completion.
Resolvers and parsers must only resolve/validate work, without executing handlers
or performing remote side effects. Refusal or a statement failure rolls back the
selection, including any recurring reschedule, and invokes no handler. Unknown
or malformed messages remain queued and may be encountered again on later polls.

`QueueDispatchError` exposes the selected `message`, a `phase`, and the original
exception through `__cause__`:

| Phase | Meaning | Poller behavior |
| --- | --- | --- |
| `commit_rejected` | PostgreSQL explicitly rejected commit with an integrity or transaction rollback error. No handler was submitted. | Logs the failure and continues polling; rolled-back work remains eligible. |
| `commit_unknown` | Commit did not return confirmation. Its outcome is uncertain. No handler was submitted. | Logs and raises, stopping this poller. |
| `committed_cleanup` | Commit succeeded, but connection cleanup failed afterwards. No handler was submitted. | Logs and raises, stopping this poller. |
| `submission` | Commit succeeded, but the executor rejected submission. | Logs and raises, stopping this poller. |

Pre-commit failures are logged and polling continues. Submission failures do not
run the handler-failure hook or mark the job as a handler failure. Once submitted,
handler exceptions use the existing failure hook and do not restore the queue row.
Callers supervising a worker must observe its task exception. Previously submitted
handlers may still be running when a poller fails; stopping polling is not a join.

This is not exactly-once execution or a durable dispatch guarantee. A process crash
between commit and submission can lose a one-shot dispatch; an uncertain commit
can leave the row present or absent. CPKit does not reinsert or immediately replay
these selections. Before restarting a poller after an uncertain or committed
failure, the operator must reconcile the identified queue/job and application
state and decide whether a new attempt is safe. Recurring rows retain their normal
future schedule after a successful commit. No schema or durable execution ledger
is introduced.

Consumer integration tests require `CPKIT_WORKER_INTEGRATION_DB_URL` pointing to a
**disposable PostgreSQL database**. They clear `cpkit.mq` and exercise actual commit
visibility, rollback, deferred commit rejection, serialization conflict, concurrent
claims, handler failure, and a simulated lost acknowledgement after a real commit.
For example:

```sh
CPKIT_WORKER_INTEGRATION_DB_URL='postgresql://localhost/cpkit_test' \
  poetry run python -m unittest discover -s tests -p 'test_jobs_dispatch_integration.py'
```

## Handler Lifetime and Drain

`create_queue_worker()` returns a callable `QueueWorker`, so existing background
factories can still invoke `worker()`. Keep that object as the lifecycle owner.
Alternatively, construct `QueueWorker` directly with the low-level handler/parser
configuration and polling options.

```python
worker = create_queue_worker(
    get_pool=get_pool, get_repo=get_repo, handlers=command_handlers,
)
poller = asyncio.create_task(worker())

# Stop further claims, including interrupting a pending poll delay.
worker.stop_polling()
await poller
result = await worker.drain(timeout=10)
if not result.complete:
    # Keep worker and shared pool alive. Inspect these handles and drain later.
    unresolved = result.unresolved
```

Stopping is terminal: each worker can run once. Controls run on the same asyncio
event loop as polling. `drain()` also requests stop, waits for polling to finish,
then waits for actual submitted invocations. `DrainResult.complete` requires
polling to have stopped and every invocation to have returned. An incomplete
result retains the original unresolved `HandlerCompletion` objects, including
message and parsed payload; shared resources must remain available. A cancelled
drain raises `CancelledError` and leaves that same context on the worker. Retry
`drain()` on that object after the handler can finish. Timeout bounds asynchronous
waiting, not synchronous database calls or arbitrary handler termination.

`worker.active_handlers` snapshots queued/running invocations. Retain a handle to
inspect it after completion: `handle.done`, `await handle.wait(timeout=...)`, or
`handle.result()` (raises `TimeoutError` while unfinished). Cancelling a waiter or
timing out never cancels the underlying invocation. `HandlerOutcome.error` records
a handler exception and `failure_hook_error` records a failure-hook exception;
completion includes repository failure updates and the custom failure hook. An
unexpected executor exception is raised by the handle. Completed handles are
pruned during polling/drain, so continuous operation does not accumulate history.

Each worker lazily creates its own thread executor. Poll cancellation/error stops
new selection but does not cancel submitted work, including work waiting for a
thread. A successful drain joins and disposes that executor. CPKit never shuts
down the application's unrelated default executor. There is no force-stop of
Python threads or external operations, automatic retry, or job-success override.

The standalone `run_queue_worker()` convenience function has no external owner;
it performs an unbounded drain before exiting, including on cancellation/error.
Its cancellation can therefore wait indefinitely for arbitrary handler code.
Use an explicitly retained worker for bounded drains and later observation.
Applications owning worker objects must integrate stop/drain before closing their
shared pool; merely cancelling a polling task is insufficient.

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
