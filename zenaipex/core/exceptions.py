"""
Zenaipex AI — Custom HTTP exceptions.

Provides typed exceptions with consistent JSON error responses.
"""
from fastapi import HTTPException, status


class ZenaipexError(HTTPException):
    """Base Zenaipex HTTP exception."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


# ── Auth Errors ───────────────────────────────────────────────────────────────

class NotAuthenticatedError(ZenaipexError):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail)


class InvalidCredentialsError(ZenaipexError):
    def __init__(self):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")


class TokenExpiredError(ZenaipexError):
    def __init__(self):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "Token has expired")


class InsufficientPermissionsError(ZenaipexError):
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class EmailNotVerifiedError(ZenaipexError):
    def __init__(self):
        super().__init__(status.HTTP_403_FORBIDDEN, "Email address not verified")


# ── Resource Errors ───────────────────────────────────────────────────────────

class NotFoundError(ZenaipexError):
    def __init__(self, resource: str = "Resource"):
        super().__init__(status.HTTP_404_NOT_FOUND, f"{resource} not found")


class ConflictError(ZenaipexError):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status.HTTP_409_CONFLICT, detail)


class ValidationError(ZenaipexError):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


# ── Tenant Errors ─────────────────────────────────────────────────────────────

class TenantNotFoundError(ZenaipexError):
    def __init__(self):
        super().__init__(status.HTTP_404_NOT_FOUND, "Company not found")


class TenantSuspendedError(ZenaipexError):
    def __init__(self):
        super().__init__(status.HTTP_403_FORBIDDEN,
                         "Your account has been suspended. Please contact the administrator for assistance.")


# ── Plan / Usage Errors ───────────────────────────────────────────────────────

class PlanLimitExceededError(ZenaipexError):
    def __init__(self, resource: str, limit: int, plan: str):
        super().__init__(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"Plan limit reached: {resource} (max {limit} on {plan} plan). "
            "Please upgrade your subscription.",
        )


class TrialExpiredError(ZenaipexError):
    def __init__(self):
        super().__init__(
            status.HTTP_402_PAYMENT_REQUIRED,
            "Your free trial has expired. Please subscribe to continue.",
        )


# ── Service Errors ────────────────────────────────────────────────────────────

class DatabaseError(ZenaipexError):
    def __init__(self, detail: str = "Database operation failed"):
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail)


class ExternalServiceError(ZenaipexError):
    def __init__(self, service: str, detail: str = ""):
        msg = f"{service} service error"
        if detail:
            msg += f": {detail}"
        super().__init__(status.HTTP_502_BAD_GATEWAY, msg)
