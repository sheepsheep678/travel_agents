"""全局异常处理器：统一 JSON 错误信封。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.core.exceptions import AppError
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details=None,
) -> JSONResponse:
    payload = {"success": False, "code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.exception("业务异常", code=exc.code, message=exc.message)
        else:
            logger.warning("业务异常", code=exc.code, message=exc.message)
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="validation_error",
            message="请求参数校验失败",
            details=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code="http_error",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "未处理的异常",
            method=request.method,
            path=request.url.path,
        )
        return _error_response(
            status_code=500,
            code="internal_error",
            message="服务器内部错误，请稍后重试",
        )
