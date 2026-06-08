"""Repository-layer exception types."""


class RepositoryError(Exception):
    """Base exception for repository and infrastructure failures."""

    def __init__(
        self,
        message: str = "Repository operation failed.",
        *,
        operation: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.retryable = retryable


class RepositoryUnavailableError(RepositoryError):
    """Raised when the database is temporarily unavailable."""


class RepositoryConflictError(RepositoryError):
    """Raised when a write conflicts with existing data."""


class RepositoryValidationError(RepositoryError):
    """Raised when the database rejects invalid data."""


class RepositoryPermissionError(RepositoryError):
    """Raised when the database denies access to an operation."""
