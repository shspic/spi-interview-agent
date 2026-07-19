import logging
from contextvars import ContextVar
from time import perf_counter
from uuid import UUID, uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)
request_id_context: ContextVar[str] = ContextVar("request_id", default="")


class RequestBodyTooLarge(Exception):
    pass


def normalize_request_id(value: str | None) -> str:
    if value:
        try:
            parsed = UUID(value.strip())
            if parsed.version == 4:
                return str(parsed)
        except (ValueError, AttributeError):
            pass
    return str(uuid4())


def get_current_request_id() -> str | None:
    return request_id_context.get() or None


class HTTPSecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = normalize_request_id(request_headers.get("x-request-id"))
        context_token = request_id_context.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        max_body_bytes = settings.max_request_body_mb * 1024 * 1024
        received_bytes = 0
        response_started = False
        response_status = 500
        started_at = perf_counter()

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > max_body_bytes:
                    raise RequestBodyTooLarge()
            return message

        async def secure_send(message):
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=()"
                )
                if scope.get("path", "").startswith("/api"):
                    headers["Cache-Control"] = "no-store"
                if "server" in headers:
                    del headers["server"]
            await send(message)

        content_length = request_headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_body_bytes:
                    await self._send_error(
                        scope,
                        limited_receive,
                        secure_send,
                        request_id,
                        413,
                        "request_body_too_large",
                        f"请求体不能超过 {settings.max_request_body_mb} MB",
                    )
                    request_id_context.reset(context_token)
                    return
            except ValueError:
                pass

        try:
            await self.app(scope, limited_receive, secure_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_error(
                scope,
                limited_receive,
                secure_send,
                request_id,
                413,
                "request_body_too_large",
                f"请求体不能超过 {settings.max_request_body_mb} MB",
            )
            response_status = 413
        except Exception as exc:
            if response_started:
                raise
            logger.error(
                "request_failed request_id=%s method=%s path=%s error_type=%s",
                request_id,
                scope.get("method", ""),
                scope.get("path", ""),
                type(exc).__name__,
            )
            await self._send_error(
                scope,
                limited_receive,
                secure_send,
                request_id,
                500,
                "internal_server_error",
                "服务器内部错误，请稍后重试",
            )
            response_status = 500
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000)
            logger.info(
                "request_completed request_id=%s method=%s path=%s "
                "status_code=%s duration_ms=%s",
                request_id,
                scope.get("method", ""),
                scope.get("path", ""),
                response_status,
                duration_ms,
            )
            request_id_context.reset(context_token)

    async def _send_error(
        self,
        scope,
        receive,
        send,
        request_id: str,
        status_code: int,
        error_code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={
                "error_code": error_code,
                "message": message,
                "request_id": request_id,
                "details": None,
                "detail": message,
            },
        )
        await response(scope, receive, send)
