# Logging

The logging package configures operational logs and carries per-request context.

## Files

- `context.py`: `request_id_ctx`, a logging filter, and compact formatter.
- `middleware.py`: FastAPI middleware that assigns/request-propagates
  `X-Request-ID` and logs inbound/outbound requests.
- `setup.py`: Root logger setup, log levels, and journald-friendly formatting.

## Runtime Flow

1. `create_cpkit_app()` configures logging during startup.
2. Request middleware sets `request_id_ctx` for each HTTP request.
3. Audit recording uses `request_id_ctx.get` as the default request id provider.
4. Log formatters include the request id so API logs and audit records can be
   correlated.

