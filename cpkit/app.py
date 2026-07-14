"""FastAPI application bootstrap helpers."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from cpkit.bundle import CpkitBundle
from cpkit.db import close_db, initialize_postgres
from cpkit.logging import configure_logging, request_logging_middleware
from cpkit.playbooks import PlaybookRunOptions, configure_playbook_run_options
from cpkit.repository import configure_repository
from cpkit.repository import get_repo as get_configured_repo

StartupHook = Callable[[], Any]
BackgroundTaskFactory = Callable[[], Awaitable[Any]]
RepoClass = Callable[[Any], Any]


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
    static_directory: str | Path | None = None,
    app_static_directory: str | Path | None = None,
    api_prefix: str = "/api",
    default_journald_identifier: str = "cp",
    playbook_run_options: PlaybookRunOptions | None = None,
) -> FastAPI:
    """Create a cpkit-managed FastAPI app with an application API subapp."""
    capability_tuple = tuple(capabilities if capabilities is not None else bundles)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        running_tasks: list[asyncio.Task[Any]] = []

        initialize_postgres(db_url)
        if repo_class is not None:
            configure_repository(repo_class=repo_class)
        elif get_repo is not None:
            configure_repository(repo_factory=get_repo)
        else:
            raise ValueError("repo_class or get_repo is required.")

        configure_playbook_run_options(playbook_run_options)
        repo = get_configured_repo()
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

        effective_background_tasks = (
            *(
                task
                for capability in capability_tuple
                for task in capability.background_tasks
            ),
            *background_tasks,
        )
        running_tasks = [
            asyncio.create_task(task_factory())
            for task_factory in effective_background_tasks
        ]

        yield

        for task in running_tasks:
            task.cancel()
        for task in running_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

        close_db()

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
