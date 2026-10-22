"""FastAPI application bootstrap helpers."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from cpkit.bundle import CpkitBundle
from cpkit.db import close_db, get_pool, initialize_postgres
from cpkit.jobs import (
    HandlerCompletion,
    QueueWorker,
    RecurringMessage,
    configure_recurring_messages,
    get_recurring_messages,
)
from cpkit.logging import configure_logging, request_logging_middleware
from cpkit.playbooks import (
    configure_playbook_run_options,
    load_playbook_run_options_from_settings,
)
from cpkit.repository import configure_repository
from cpkit.repository import get_repo as get_configured_repo

StartupHook = Callable[[], Any]
BackgroundTaskFactory = Callable[[], Awaitable[Any]]
RepoClass = Callable[[Any], Any]


@dataclass(frozen=True)
class ShutdownResult:
    """Application cleanup status; unfinished work still owns shared resources."""

    pool_closed: bool
    polling_stopped: bool
    unresolved: tuple[HandlerCompletion, ...]
    pending_tasks: tuple[asyncio.Task[Any], ...]
    task_errors: tuple[BaseException, ...]

    @property
    def complete(self) -> bool:
        return (
            self.pool_closed
            and self.polling_stopped
            and not self.unresolved
            and not self.pending_tasks
        )


class AppShutdownIncomplete(RuntimeError):
    """Shutdown timed out; retain the runtime and retry its shutdown later."""

    def __init__(self, runtime: "AppRuntime", result: ShutdownResult):
        self.runtime = runtime
        self.result = result
        super().__init__(
            f"CPKit shutdown incomplete: {len(result.unresolved)} handler(s), "
            f"{len(result.pending_tasks)} background task(s) unresolved; pool kept open"
        )


class AppRuntime:
    """Retained owner for app tasks, registered workers, and shared-pool closure.

    Controls use the lifespan event loop. Cancellation/timeout keeps this owner
    available as app.state.cpkit_runtime for later observation and shutdown.
    """

    def __init__(
        self,
        workers: tuple[QueueWorker, ...],
        close_pool: Callable[[], None],
        current_pool: Callable[[], Any],
    ):
        self.workers = workers
        self._tasks: list[asyncio.Task[Any]] = []
        self._close_pool = close_pool
        self._current_pool = current_pool
        self._pool: Any | None = None
        self._pool_closed = False
        self._stop_requested = False
        self._shutdown_lock = asyncio.Lock()

    @property
    def pool(self) -> Any | None:
        """Original shared pool, retained even after a failed/cancelled shutdown."""
        return self._pool

    @property
    def status(self) -> ShutdownResult:
        return ShutdownResult(
            pool_closed=self._pool_closed,
            polling_stopped=all(worker.polling_stopped for worker in self.workers),
            unresolved=tuple(
                handle for worker in self.workers for handle in worker.active_handlers
            ),
            pending_tasks=tuple(task for task in self._tasks if not task.done()),
            task_errors=tuple(
                err
                for task in self._tasks
                if task.done()
                and not task.cancelled()
                and (err := task.exception()) is not None
            ),
        )

    async def shutdown(self, timeout: float | None = None) -> ShutdownResult:
        """Stop once, drain/join actual work, then close the shared pool.

        Timeout returns an incomplete result. Cancellation propagates. Neither
        disposes resources while registered handlers/background tasks remain.
        Repeated calls continue cleanup rather than repeating dispatch.
        """
        if not self._stop_requested:
            for worker in self.workers:
                worker.stop_polling()
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            self._stop_requested = True
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                async with self._shutdown_lock:
                    if self._pool_closed:
                        return self.status
                    pending = self.status.pending_tasks
                    if pending:
                        # Observing tasks with wait() does not cancel their
                        # cleanup a second time if this shutdown is cancelled.
                        await asyncio.wait(pending)
                    if self.workers:
                        drains = await asyncio.gather(
                            *(worker.drain() for worker in self.workers),
                            return_exceptions=True,
                        )
                        errors = [
                            drain
                            for drain in drains
                            if isinstance(drain, BaseException)
                        ]
                        if errors:
                            raise BaseExceptionGroup(
                                "CPKit worker drain failures", errors
                            )
                        if any(not drain.complete for drain in drains):
                            return self.status
                    if self.pool is not None and self._current_pool() is not self.pool:
                        raise RuntimeError(
                            "Shared pool changed since application startup"
                        )
                    self._close_pool()
                    self._pool_closed = True
        except TimeoutError:
            if not deadline.expired():
                raise
        return self.status


def create_cpkit_app(
    *,
    title: str,
    version: str,
    repo_class: RepoClass | None = None,
    get_repo: Callable[[], Any] | None = None,
    db_url: str | None,
    capabilities: Iterable[CpkitBundle] | None = None,
    bundles: Iterable[CpkitBundle] = (),
    routers: Iterable[APIRouter] = (),
    startup_hooks: Iterable[StartupHook] = (),
    background_tasks: Iterable[BackgroundTaskFactory] = (),
    recurring_messages: Iterable[RecurringMessage] = (),
    static_directory: str | Path | None = None,
    app_static_directory: str | Path | None = None,
    api_prefix: str = "/api",
    default_journald_identifier: str = "cp",
    shutdown_timeout: float | None = None,
) -> FastAPI:
    """Create a cpkit-managed FastAPI app with an application API subapp."""
    capability_tuple = tuple(capabilities if capabilities is not None else bundles)

    bundle_background_tasks = tuple(
        task for capability in capability_tuple for task in capability.background_tasks
    )
    workers = tuple(
        dict.fromkeys(
            (
                *(
                    capability.queue_worker
                    for capability in capability_tuple
                    if capability.queue_worker is not None
                ),
                *(
                    factory
                    for factory in bundle_background_tasks
                    if isinstance(factory, QueueWorker)
                ),
            )
        )
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        previous = getattr(_app.state, "cpkit_runtime", None)
        if previous is not None and not previous.status.complete:
            raise RuntimeError("Previous CPKit runtime has unfinished shutdown")
        runtime = AppRuntime(workers, close_db, get_pool)
        _app.state.cpkit_runtime = runtime
        failure = None
        try:
            initialize_postgres(db_url)
            runtime._pool = get_pool()
            if repo_class is not None:
                configure_repository(repo_class=repo_class)
            elif get_repo is not None:
                configure_repository(repo_factory=get_repo)
            else:
                raise ValueError("repo_class or get_repo is required.")

            repo = get_configured_repo()
            configure_recurring_messages(recurring_messages)
            repo.ensure_recurring_messages(get_recurring_messages())
            configure_playbook_run_options(
                load_playbook_run_options_from_settings(repo)
            )
            configure_logging(
                repo,
                force=True,
                default_journald_identifier=default_journald_identifier,
            )
            effective_startup_hooks = (
                *(
                    hook
                    for capability in capability_tuple
                    for hook in capability.startup_hooks
                ),
                *startup_hooks,
            )
            for hook in effective_startup_hooks:
                result = hook()
                if inspect.isawaitable(result):
                    await result

            # Keep already-created tasks reachable if a later factory fails.
            for task_factory in chain(bundle_background_tasks, background_tasks):
                if (
                    isinstance(task_factory, QueueWorker)
                    and task_factory not in runtime.workers
                ):
                    runtime.workers = (*runtime.workers, task_factory)
                runtime._tasks.append(asyncio.create_task(task_factory()))
            yield
        except BaseException as err:
            failure = err

        try:
            result = await runtime.shutdown(
                timeout=(
                    0
                    if isinstance(failure, asyncio.CancelledError)
                    else shutdown_timeout
                ),
            )
        except BaseException as err:
            if failure is not None:
                raise err from failure
            raise
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        if not result.complete:
            raise AppShutdownIncomplete(runtime, result) from failure
        failures = ([failure] if failure is not None else []) + list(result.task_errors)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("CPKit application/background failures", failures)

    app = FastAPI(lifespan=lifespan)
    api = FastAPI(title=title, version=version)

    effective_routers = (
        *(router for capability in capability_tuple for router in capability.routers),
        *routers,
    )
    for router in effective_routers:
        api.include_router(router)

    app.mount(api_prefix, api)

    if app_static_directory is not None:
        app.mount(
            "/app",
            StaticFiles(directory=Path(app_static_directory), html=True),
            name="app_webapp",
        )

    if static_directory is not None:
        app.mount(
            "/",
            StaticFiles(directory=Path(static_directory), html=True),
            name="webapp",
        )

    @app.middleware("http")
    async def dispatch(request: Request, call_next):
        return await request_logging_middleware(request, call_next)

    return app
