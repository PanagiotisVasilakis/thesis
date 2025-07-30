"""Custom exception hierarchy for the ML service."""

class MLServiceError(Exception):
    """Base class for service specific exceptions."""


class ModelError(MLServiceError):
    """Raised for errors related to model loading or inference."""


class RequestValidationError(MLServiceError):
    """Raised when a request fails validation or contains invalid data."""


class NEFConnectionError(MLServiceError):
    """Raised when communication with the NEF emulator fails."""


class ResourceNotFoundError(MLServiceError):
    """Raised when a requested resource is not found."""
