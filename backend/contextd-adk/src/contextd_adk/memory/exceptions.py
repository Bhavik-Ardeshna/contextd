"""
Memory-specific exceptions.

Provides exception classes for memory operations that inherit from
the SDK's base exception hierarchy.
"""

from typing import Any

from contextd_adk.exceptions import ErrorCategory, ErrorSeverity, OrchestratorError


class MemoryError(OrchestratorError):
    """
    Base exception for memory-related errors.

    All memory exceptions inherit from this class.
    """

    default_message = "Memory operation failed"
    default_error_code = "MEMORY_ERROR"
    default_category = ErrorCategory.INTERNAL
    default_severity = ErrorSeverity.MEDIUM  # Memory errors usually shouldn't break the app


class MemoryConfigurationError(MemoryError):
    """
    Raised when there's a memory configuration issue.

    Examples:
        - Missing vector-store host
        - Invalid embedder configuration
        - Missing required identifiers
    """

    default_message = "Memory configuration error"
    default_error_code = "MEMORY_CONFIG_ERROR"
    default_category = ErrorCategory.CONFIGURATION
    default_severity = ErrorSeverity.HIGH

    def __init__(
        self,
        message: str | None = None,
        *,
        config_key: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if config_key:
            context["config_key"] = config_key
        super().__init__(message, context=context, **kwargs)


class MemoryNotEnabledError(MemoryError):
    """
    Raised when memory operations are attempted but memory is disabled.
    """

    default_message = "Memory is not enabled"
    default_error_code = "MEMORY_NOT_ENABLED"
    default_category = ErrorCategory.CONFIGURATION
    default_severity = ErrorSeverity.LOW


class MemoryConnectionError(MemoryError):
    """
    Raised when connection to vector store fails.

    Examples:
        - Milvus connection failed
        - Vector store unavailable
    """

    default_message = "Failed to connect to vector store"
    default_error_code = "MEMORY_CONNECTION_ERROR"
    default_category = ErrorCategory.NETWORK
    default_severity = ErrorSeverity.HIGH

    def __init__(
        self,
        message: str | None = None,
        *,
        vector_store: str | None = None,
        host: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if vector_store:
            context["vector_store"] = vector_store
        if host:
            context["host"] = host
        super().__init__(message, context=context, **kwargs)


class MemorySearchError(MemoryError):
    """
    Raised when memory search fails.

    Examples:
        - Search query invalid
        - Vector search failed
    """

    default_message = "Memory search failed"
    default_error_code = "MEMORY_SEARCH_ERROR"
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        query: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if query:
            context["query"] = query
        super().__init__(message, context=context, **kwargs)


class MemoryAddError(MemoryError):
    """
    Raised when adding memory fails.

    Examples:
        - Failed to extract facts
        - Failed to store in vector DB
    """

    default_message = "Failed to add memory"
    default_error_code = "MEMORY_ADD_ERROR"
    default_severity = ErrorSeverity.MEDIUM


class MemoryDeleteError(MemoryError):
    """
    Raised when deleting memory fails.
    """

    default_message = "Failed to delete memory"
    default_error_code = "MEMORY_DELETE_ERROR"
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        memory_id: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if memory_id:
            context["memory_id"] = memory_id
        super().__init__(message, context=context, **kwargs)


class MemoryUpdateError(MemoryError):
    """
    Raised when updating memory fails.
    """

    default_message = "Failed to update memory"
    default_error_code = "MEMORY_UPDATE_ERROR"
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        memory_id: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if memory_id:
            context["memory_id"] = memory_id
        super().__init__(message, context=context, **kwargs)


class MemoryIdentifierError(MemoryError):
    """
    Raised when required memory identifiers are missing or invalid.

    Examples:
        - Missing user_id for user-level isolation
        - Missing required identifiers
    """

    default_message = "Invalid or missing memory identifiers"
    default_error_code = "MEMORY_IDENTIFIER_ERROR"
    default_category = ErrorCategory.VALIDATION
    default_severity = ErrorSeverity.MEDIUM

    def __init__(
        self,
        message: str | None = None,
        *,
        required_identifier: str | None = None,
        isolation_level: str | None = None,
        **kwargs: Any,
    ):
        context = kwargs.pop("context", {}) or {}
        if required_identifier:
            context["required_identifier"] = required_identifier
        if isolation_level:
            context["isolation_level"] = isolation_level
        super().__init__(message, context=context, **kwargs)
