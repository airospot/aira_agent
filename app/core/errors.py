"""Shared application errors. No feature business logic."""


class AppError(Exception):
    """Base application error."""


class CatalogProviderError(AppError):
    """Catalog / database provider unavailable or misconfigured."""


class NotFoundError(AppError):
    """Requested resource does not exist."""


class ValidationError(AppError):
    """Invalid input or missing required configuration."""
