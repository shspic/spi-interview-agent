from contextlib import asynccontextmanager
import re

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.db.database import SessionLocal, init_db
from app.api.files import router as files_router
from app.api.knowledge import router as knowledge_router
from app.api.llm import router as llm_router
from app.api.chat import router as chat_router
from app.api.history import router as history_router
from app.api.jobs import router as jobs_router
from app.api.interview import router as interview_router
from app.api.interview_records import router as interview_records_router
from app.api.web_search import router as web_search_router
from app.api.agent import router as agent_router
from app.api.system_status import router as system_status_router
from app.api.auth import router as auth_router
from app.api.profile import router as profile_router
from app.api.target_jobs import router as target_jobs_router
from app.api.interview_sessions import router as interview_sessions_router
from app.api.improvement_tasks import router as improvement_tasks_router
from app.api.resume_project_descriptions import (
    router as resume_project_descriptions_router,
)
from app.api.admin import router as admin_router
from app.api.usage import router as usage_router
from app.api.account import router as account_router
from app.services.registration_setting_service import (
    RegistrationSettingError,
    ensure_registration_setting,
)
from app.core.config import settings
from app.core.http_security import HTTPSecurityMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_registration_setting(db)
    except RegistrationSettingError:
        db.rollback()
    finally:
        db.close()
    yield


app = FastAPI(
    title="AI Interview RAG Coach API",
    description="Backend API for AI Interview RAG Coach",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(HTTPSecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Idempotency-Key",
        "X-CSRF-Token",
        "X-Request-ID",
    ],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)

WINDOWS_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")
UNIX_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])/(?:home|tmp|var|opt)/[^\s\"']+")
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)\b(?:authorization|cookie|password|invite_code|api_key|jwt|token)"
    r"\s*[:=]\s*[^\s,;]+"
)


def sanitize_error_detail(value):
    if isinstance(value, str):
        sanitized = WINDOWS_PATH_PATTERN.sub("[已脱敏路径]", value)
        sanitized = UNIX_PATH_PATTERN.sub("[已脱敏路径]", sanitized)
        sanitized = SECRET_VALUE_PATTERN.sub("[已脱敏敏感字段]", sanitized)
        return sanitized[:500]
    if isinstance(value, list):
        return [sanitize_error_detail(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key)[:64]: sanitize_error_detail(item)
            for key, item in list(value.items())[:20]
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "请求失败"


@app.exception_handler(StarletteHTTPException)
async def safe_http_exception_handler(request, exc):
    request_id = getattr(request.state, "request_id", "")
    if exc.status_code == 500:
        detail = "服务器内部错误，请稍后重试"
        error_code = "internal_server_error"
        details = None
    else:
        detail = sanitize_error_detail(exc.detail)
        error_code = (
            detail.get("error_code", f"http_{exc.status_code}")
            if isinstance(detail, dict)
            else f"http_{exc.status_code}"
        )
        details = detail if isinstance(detail, (dict, list)) else None
    message = (
        detail.get("message", "请求失败")
        if isinstance(detail, dict)
        else str(detail)
    )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error_code": error_code,
            "message": message,
            "request_id": request_id,
            "details": details,
            "detail": detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def safe_validation_exception_handler(request, exc):
    request_id = getattr(request.state, "request_id", "")
    sanitized_errors = [
        {
            "type": item.get("type", "value_error"),
            "loc": list(item.get("loc", [])),
            "msg": item.get("msg", "输入内容无效"),
        }
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "validation_error",
            "message": "请求内容不符合接口要求",
            "request_id": request_id,
            "details": sanitized_errors,
            "detail": sanitized_errors,
        },
    )

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(files_router, prefix="/api", tags=["files"])
app.include_router(knowledge_router, prefix="/api", tags=["知识库"])
app.include_router(llm_router, prefix="/api", tags=["大模型"])
app.include_router(chat_router, prefix="/api", tags=["RAG 问答"])
app.include_router(history_router, prefix="/api", tags=["历史记录"])
app.include_router(jobs_router, prefix="/api", tags=["岗位分析"])
app.include_router(interview_router, prefix="/api", tags=["模拟面试"])
app.include_router(interview_records_router, prefix="/api", tags=["模拟面试记录"])
app.include_router(web_search_router, prefix="/api", tags=["联网搜索"])
app.include_router(agent_router, prefix="/api", tags=["LangGraph Agent"])
app.include_router(system_status_router, prefix="/api", tags=["系统状态"])
app.include_router(auth_router, prefix="/api", tags=["认证"])
app.include_router(profile_router, prefix="/api", tags=["用户资料"])
app.include_router(target_jobs_router, prefix="/api", tags=["目标岗位"])
app.include_router(interview_sessions_router, prefix="/api", tags=["面试训练会话"])
app.include_router(improvement_tasks_router, prefix="/api", tags=["面试改进任务"])
app.include_router(
    resume_project_descriptions_router,
    prefix="/api",
    tags=["简历项目描述"],
)
app.include_router(usage_router, prefix="/api", tags=["用户用量"])
app.include_router(admin_router, prefix="/api", tags=["管理员"])
app.include_router(account_router, prefix="/api", tags=["账号数据"])
