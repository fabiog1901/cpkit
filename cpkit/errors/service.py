"""Service-layer exception types and repository error translation."""

from .repository import (
    RepositoryConflictError,
    RepositoryError,
    RepositoryPermissionError,
    RepositoryUnavailableError,
    RepositoryValidationError,
)


class ServiceError(Exception):
    """Base exception for errors that may be shown in a UI or API response."""

    default_title = "Error"
    default_message = "Something went wrong. Please try again."

    def __init__(
        self,
        message: str | None = None,
        *,
        title: str | None = None,
    ) -> None:
        self.user_title = title or self.default_title
        self.user_message = message or self.default_message
        super().__init__(self.user_message)


class ServiceUnavailableError(ServiceError):
    default_title = "Temporarily Unavailable"
    default_message = "The service is temporarily unavailable. Please try again."


class ServiceConflictError(ServiceError):
    default_title = "Conflict"
    default_message = "The requested change conflicts with existing data."


class ServiceValidationError(ServiceError):
    default_title = "Invalid Request"
    default_message = "The submitted data is invalid."


class ServiceAuthorizationError(ServiceError):
    default_title = "Not Authorized"
    default_message = "You are not authorized to perform this action."


class ServiceNotFoundError(ServiceError):
    default_title = "Not Found"
    default_message = "The requested item could not be found."


def from_repository_error(
    err: RepositoryError,
    *,
    unavailable_message: str | None = None,
    conflict_message: str | None = None,
    validation_message: str | None = None,
    permission_message: str | None = None,
    fallback_message: str | None = None,
    fallback_title: str | None = None,
) -> ServiceError:
    """Translate a repository exception into a service exception."""

    if isinstance(err, RepositoryUnavailableError):
        return ServiceUnavailableError(unavailable_message)
    if isinstance(err, RepositoryConflictError):
        return ServiceConflictError(conflict_message)
    if isinstance(err, RepositoryValidationError):
        return ServiceValidationError(validation_message)
    if isinstance(err, RepositoryPermissionError):
        return ServiceAuthorizationError(permission_message)
    return ServiceError(fallback_message, title=fallback_title)
