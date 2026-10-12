"""Application-wide exception hierarchy.

All user-visible errors should be instances of ``AppError`` or a subclass.
That makes it easy for UI code to catch exactly the errors it should show
to the user and let everything else propagate normally.
"""


class AppError(Exception):
    """Base class for expected, user-facing errors."""


class ValidationError(AppError):
    """Raised when user input violates a business rule."""


class ConflictError(AppError):
    """Raised when an operation conflicts with existing data (e.g. duplicate name)."""


class NotFoundError(AppError):
    """Raised when a requested record does not exist."""


class DatabaseError(AppError):
    """Raised when the database layer encounters an unrecoverable problem."""


class SingleInstanceError(AppError):
    """Raised when a second copy of the app tries to start."""
