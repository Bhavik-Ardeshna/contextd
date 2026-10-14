"""
Session exceptions.

Custom exceptions for session management operations.
"""


class SessionError(Exception):
    """Base exception for session operations."""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message)
        self.session_id = session_id
        self.original_error = original_error


class SessionNotEnabledError(SessionError):
    """Raised when session operations are attempted but sessions are disabled."""

    pass


class SessionConfigurationError(SessionError):
    """Raised when session configuration is invalid."""

    pass


class SessionConnectionError(SessionError):
    """Raised when connection to Redis fails."""

    pass


class SessionNotFoundError(SessionError):
    """Raised when a session is not found."""

    pass


class SessionMessageLimitError(SessionError):
    """Raised when session message limit is exceeded."""

    def __init__(
        self,
        message: str,
        session_id: str,
        current_count: int,
        max_messages: int,
        original_error: Exception | None = None,
    ):
        super().__init__(message, session_id, original_error)
        self.current_count = current_count
        self.max_messages = max_messages
