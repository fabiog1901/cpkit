# Errors

The errors package defines cpkit's exception layers. The layers are deliberately
separate so low-level DB details do not leak directly into API responses.

## Files

- `repository.py`: Errors raised by repository/database operations.
- `service.py`: User-facing service errors and repository-to-service
  translation.
- `http.py`: Service-to-FastAPI HTTP response translation.

## Error Flow

1. DB helpers raise `RepositoryError` subclasses.
2. Services catch repository errors and call `from_repository_error()`.
3. Routers catch `ServiceError` and call `raise_http_from_service_error()`.

This keeps SQL and driver details out of routers while still letting the UI show
clear messages such as "not found", "not authorized", or "temporarily
unavailable".

