"""cpkit TODO example application."""

import os
from pathlib import Path

from cpkit import create_cpkit_app, create_cpkit_bundle, template_webapp_directory

from .api import router as todos_router
from .models import COMMAND_MODELS
from .repos import Repo
from .workers import COMMAND_HANDLERS

CPKIT_DB_URL = os.getenv("CPKIT_DB_URL")
WEBAPP_DIR = Path(__file__).resolve().parents[1] / "webapp"

cpkit_capabilities = create_cpkit_bundle(
    command_models=COMMAND_MODELS,
    command_handlers=COMMAND_HANDLERS,
)

app = create_cpkit_app(
    title="todo-app",
    version="0.1.0",
    repo_class=Repo,
    db_url=CPKIT_DB_URL,
    capabilities=(cpkit_capabilities,),
    routers=(todos_router,),
    static_directory=template_webapp_directory(),
    app_static_directory=WEBAPP_DIR,
    default_journald_identifier="todo-app",
)
