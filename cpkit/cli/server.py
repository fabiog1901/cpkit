"""ASGI server helpers for cpkit application CLIs."""

import uvicorn


def serve_uvicorn(
    app_import: str,
    *,
    host: str,
    port: int,
    reload: bool,
    log_level: str,
) -> None:
    """Run an ASGI app through Uvicorn."""
    uvicorn.run(
        app_import,
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )
