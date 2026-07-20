from fastapi import HTTPException, Response, status

from app.core.config import settings


SUNSET_AT = "Wed, 30 Sep 2026 23:59:59 GMT"


def enforce_sync_long_task_policy(response: Response, replacement: str) -> None:
    """仅在测试兼容模式执行旧同步长任务，生产始终拒绝。"""
    headers = {
        "Deprecation": "true",
        "Sunset": SUNSET_AT,
        "Link": f'<{replacement}>; rel="successor-version"',
        "Cache-Control": "no-store",
    }
    if not settings.enable_sync_long_task_compat:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error_code": "sync_long_task_deprecated",
                "message": "该同步长任务入口已停用，请改用后台任务接口。",
                "replacement": replacement,
            },
            headers=headers,
        )
    for name, value in headers.items():
        response.headers[name] = value
