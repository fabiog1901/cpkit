"""FastAPI translation helpers for framework service errors."""

from fastapi import HTTPException, status

from .service import (
    ServiceAuthorizationError,
    ServiceConflictError,
    ServiceError,
    ServiceNotFoundError,
    ServiceUnavailableError,
    ServiceValidationError,
)


def raise_http_from_service_error(err: ServiceError) -> None:
    """Raise an HTTPException that matches a service-layer error."""
    if isinstance(err, ServiceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=err.user_message,
        )
    if isinstance(err, ServiceValidationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err.user_message,
        )
    if isinstance(err, ServiceConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=err.user_message,
        )
    if isinstance(err, ServiceAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=err.user_message,
        )
    if isinstance(err, ServiceUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=err.user_message,
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=err.user_message,
    )
