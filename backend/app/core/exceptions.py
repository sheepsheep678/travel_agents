"""业务异常定义。

所有可预期的业务错误都继承 :class:`AppError`，由全局异常处理器统一转成
``{"success": false, "code": ..., "message": ...}`` 响应；路由和 service
里不再到处拼 ``HTTPException``。
"""

from __future__ import annotations

from typing import Any, Optional


class AppError(Exception):
    """业务异常基类。"""

    status_code: int = 400
    code: str = "app_error"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_failed"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"
