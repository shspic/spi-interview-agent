import os
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

BASE_DIR = Path(__file__).resolve().parents[2]
if os.getenv("SKIP_DOTENV") != "1":
    load_dotenv(BASE_DIR / ".env")


class Settings(BaseModel):
    app_name: str = "AI Interview RAG Coach"
    app_environment: str = os.getenv("APP_ENVIRONMENT", "development")
    upload_dir: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    chroma_persist_dir: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
    sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", "./data/app.db")
    database_url: str = os.getenv("DATABASE_URL", "").strip()
    enable_legacy_schema_patches: bool = (
        os.getenv("ENABLE_LEGACY_SCHEMA_PATCHES", "false").lower() == "true"
    )
    embedding_model_name: str = os.getenv(
        "EMBEDDING_MODEL_NAME",
        "BAAI/bge-small-zh-v1.5",
    )
    evidence_max_distance: float = float(
        os.getenv("EVIDENCE_MAX_DISTANCE", "0.8")
    )
    retrieval_candidate_multiplier: int = Field(
        default=int(os.getenv("RETRIEVAL_CANDIDATE_MULTIPLIER", "3")),
        ge=1,
        le=10,
    )
    retrieval_max_candidates: int = Field(
        default=int(os.getenv("RETRIEVAL_MAX_CANDIDATES", "40")),
        ge=1,
        le=100,
    )

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    )
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    registration_invite_code: str = os.getenv("REGISTRATION_INVITE_CODE", "")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")
    jwt_expire_minutes: int = int(os.getenv("AUTH_ACCESS_TOKEN_MINUTES", "15"))
    auth_refresh_token_days: int = Field(
        default=int(os.getenv("AUTH_REFRESH_TOKEN_DAYS", "7")), ge=1, le=90
    )
    auth_max_active_sessions: int = Field(
        default=int(os.getenv("AUTH_MAX_ACTIVE_SESSIONS", "5")), ge=1, le=50
    )
    auth_cookie_secure: bool = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
    auth_cookie_samesite: str = os.getenv("AUTH_COOKIE_SAMESITE", "lax")
    auth_cookie_domain: str | None = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
    auth_access_cookie_name: str = os.getenv(
        "AUTH_ACCESS_COOKIE_NAME", "spi_access"
    )
    auth_refresh_cookie_name: str = os.getenv(
        "AUTH_REFRESH_COOKIE_NAME", "spi_refresh"
    )
    auth_csrf_cookie_name: str = os.getenv("AUTH_CSRF_COOKIE_NAME", "spi_csrf")
    auth_access_cookie_path: str = "/api"
    auth_refresh_cookie_path: str = "/api/auth"
    auth_csrf_cookie_path: str = "/"
    auth_csrf_secret: str = os.getenv(
        "AUTH_CSRF_SECRET",
        os.getenv("JWT_SECRET_KEY", ""),
    )
    auth_require_origin_check: bool = (
        os.getenv("AUTH_REQUIRE_ORIGIN_CHECK", "true").lower() == "true"
    )
    app_timezone: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    daily_chat_limit: int = int(os.getenv("DAILY_CHAT_LIMIT", "10"))
    daily_job_analysis_limit: int = int(
        os.getenv("DAILY_JOB_ANALYSIS_LIMIT", "3")
    )
    daily_interview_evaluation_limit: int = int(
        os.getenv("DAILY_INTERVIEW_EVALUATION_LIMIT", "5")
    )
    daily_multi_agent_task_limit: int = int(
        os.getenv("DAILY_MULTI_AGENT_TASK_LIMIT", "3")
    )
    data_retention_days: int = int(os.getenv("DATA_RETENTION_DAYS", "7"))
    job_poll_interval_seconds: float = Field(
        default=float(os.getenv("JOB_POLL_INTERVAL_SECONDS", "1")),
        ge=0.1,
        le=60,
    )
    job_lease_seconds: int = Field(
        default=int(os.getenv("JOB_LEASE_SECONDS", "60")),
        ge=10,
        le=3600,
    )
    job_heartbeat_seconds: int = Field(
        default=int(os.getenv("JOB_HEARTBEAT_SECONDS", "10")),
        ge=2,
        le=300,
    )
    job_max_attempts: int = Field(
        default=int(os.getenv("JOB_MAX_ATTEMPTS", "3")),
        ge=1,
        le=10,
    )
    worker_concurrency: int = Field(
        default=int(os.getenv("WORKER_CONCURRENCY", "1")),
        ge=1,
        le=16,
    )
    job_history_days: int = Field(
        default=int(os.getenv("JOB_HISTORY_DAYS", "30")),
        ge=1,
        le=365,
    )

    trusted_proxy_cidrs: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("APP_TRUSTED_PROXY_CIDRS", "").split(",")
        if value.strip()
    )
    cors_allowed_origins: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            (
                ""
                if os.getenv("APP_ENVIRONMENT", "development").lower()
                == "production"
                else "http://localhost:5173,http://127.0.0.1:5173"
            ),
        ).split(",")
        if value.strip()
    )
    rate_limit_hash_salt: str = os.getenv("RATE_LIMIT_HASH_SALT", "")

    max_request_body_mb: int = Field(
        default=int(os.getenv("MAX_REQUEST_BODY_MB", "25")),
        ge=1,
        le=200,
    )
    max_upload_file_size_mb: int = Field(
        default=int(os.getenv("MAX_UPLOAD_FILE_SIZE_MB", "20")),
        ge=1,
        le=100,
    )
    max_upload_files_per_request: int = Field(
        default=int(os.getenv("MAX_UPLOAD_FILES_PER_REQUEST", "1")),
        ge=1,
        le=5,
    )
    max_user_storage_mb: int = Field(
        default=int(os.getenv("MAX_USER_STORAGE_MB", "200")),
        ge=1,
        le=10_000,
    )
    max_pdf_pages: int = Field(
        default=int(os.getenv("MAX_PDF_PAGES", "500")),
        ge=1,
        le=2_000,
    )
    max_text_line_chars: int = Field(
        default=int(os.getenv("MAX_TEXT_LINE_CHARS", "100000")),
        ge=1_000,
        le=1_000_000,
    )
    max_filename_chars: int = Field(
        default=int(os.getenv("MAX_FILENAME_CHARS", "180")),
        ge=32,
        le=240,
    )

    max_chat_input_chars: int = Field(
        default=int(os.getenv("MAX_CHAT_INPUT_CHARS", "6000")),
        ge=100,
        le=30_000,
    )
    max_interview_answer_chars: int = Field(
        default=int(os.getenv("MAX_INTERVIEW_ANSWER_CHARS", "12000")),
        ge=100,
        le=50_000,
    )
    max_job_description_chars: int = Field(
        default=int(os.getenv("MAX_JOB_DESCRIPTION_CHARS", "30000")),
        ge=1_000,
        le=100_000,
    )
    max_profile_text_chars: int = Field(
        default=int(os.getenv("MAX_PROFILE_TEXT_CHARS", "5000")),
        ge=100,
        le=30_000,
    )
    max_task_input_chars: int = Field(
        default=int(os.getenv("MAX_TASK_INPUT_CHARS", "12000")),
        ge=100,
        le=50_000,
    )

    login_rate_limit_attempts: int = Field(
        default=int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "10")), ge=1, le=100
    )
    login_rate_limit_window_seconds: int = Field(
        default=int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")),
        ge=10,
        le=86_400,
    )
    register_rate_limit_attempts: int = Field(
        default=int(os.getenv("REGISTER_RATE_LIMIT_ATTEMPTS", "5")), ge=1, le=100
    )
    register_rate_limit_window_seconds: int = Field(
        default=int(os.getenv("REGISTER_RATE_LIMIT_WINDOW_SECONDS", "1800")),
        ge=10,
        le=86_400,
    )
    upload_rate_limit_attempts: int = Field(
        default=int(os.getenv("UPLOAD_RATE_LIMIT_ATTEMPTS", "20")), ge=1, le=500
    )
    upload_rate_limit_window_seconds: int = Field(
        default=int(os.getenv("UPLOAD_RATE_LIMIT_WINDOW_SECONDS", "3600")),
        ge=10,
        le=86_400,
    )
    password_change_rate_limit_attempts: int = Field(
        default=int(os.getenv("PASSWORD_CHANGE_RATE_LIMIT_ATTEMPTS", "5")),
        ge=1,
        le=100,
    )
    password_change_rate_limit_window_seconds: int = Field(
        default=int(os.getenv("PASSWORD_CHANGE_RATE_LIMIT_WINDOW_SECONDS", "3600")),
        ge=10,
        le=86_400,
    )
    chat_burst_rate_limit_attempts: int = Field(
        default=int(os.getenv("CHAT_BURST_RATE_LIMIT_ATTEMPTS", "10")),
        ge=1,
        le=500,
    )
    chat_burst_rate_limit_window_seconds: int = Field(
        default=int(os.getenv("CHAT_BURST_RATE_LIMIT_WINDOW_SECONDS", "60")),
        ge=10,
        le=3_600,
    )
    admin_write_rate_limit_attempts: int = Field(
        default=int(os.getenv("ADMIN_WRITE_RATE_LIMIT_ATTEMPTS", "10")),
        ge=1,
        le=100,
    )
    admin_write_rate_limit_window_seconds: int = Field(
        default=int(os.getenv("ADMIN_WRITE_RATE_LIMIT_WINDOW_SECONDS", "3600")),
        ge=10,
        le=86_400,
    )

    @model_validator(mode="after")
    def validate_security_configuration(self):
        environment = self.app_environment.strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENVIRONMENT 只能是 development、test 或 production")
        self.app_environment = environment

        for value in self.trusted_proxy_cidrs:
            ip_network(value, strict=False)

        for origin in self.cors_allowed_origins:
            parsed = urlsplit(origin)
            if origin == "*" or parsed.scheme not in {"http", "https"}:
                raise ValueError("CORS_ALLOWED_ORIGINS 必须是明确的 HTTP(S) 来源")
            if not parsed.netloc or parsed.path not in {"", "/"}:
                raise ValueError("CORS_ALLOWED_ORIGINS 不得包含路径")

        same_site = self.auth_cookie_samesite.strip().lower()
        if same_site not in {"lax", "strict", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE 只能是 lax、strict 或 none")
        if same_site == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SAMESITE=none 时必须启用 Secure Cookie")
        self.auth_cookie_samesite = same_site

        if environment == "production" and not self.auth_cookie_secure:
            raise ValueError("生产环境必须启用 Secure Cookie")
        if environment == "production" and self.jwt_secret_key.strip() in {
            "",
            "change-me",
        }:
            raise ValueError("生产环境必须配置 JWT_SECRET_KEY")
        if environment == "production" and self.auth_csrf_secret.strip() in {
            "",
            "change-me",
            self.jwt_secret_key.strip(),
        }:
            raise ValueError("生产环境必须配置独立的 AUTH_CSRF_SECRET")
        if environment == "production" and self.enable_legacy_schema_patches:
            raise ValueError("生产环境禁止启用旧版运行时 Schema 补丁")
        configured_database_url = self.database_url.strip()
        if configured_database_url:
            scheme = urlsplit(configured_database_url).scheme.lower()
            if scheme not in {"sqlite", "postgresql+psycopg"}:
                raise ValueError(
                    "DATABASE_URL 仅支持 sqlite 或 postgresql+psycopg"
                )
        if environment == "production":
            if not configured_database_url:
                raise ValueError("生产环境必须显式配置 DATABASE_URL")
            if not configured_database_url.startswith("postgresql+psycopg://"):
                raise ValueError("生产环境 DATABASE_URL 必须使用 PostgreSQL psycopg 驱动")

        if self.job_heartbeat_seconds * 2 >= self.job_lease_seconds:
            raise ValueError("JOB_HEARTBEAT_SECONDS 必须小于 lease 时间的一半")

        cookie_names = {
            self.auth_access_cookie_name,
            self.auth_refresh_cookie_name,
            self.auth_csrf_cookie_name,
        }
        if len(cookie_names) != 3 or any(not name.strip() for name in cookie_names):
            raise ValueError("认证 Cookie 名称必须非空且互不相同")

        if self.max_request_body_mb < self.max_upload_file_size_mb:
            raise ValueError("MAX_REQUEST_BODY_MB 不得小于 MAX_UPLOAD_FILE_SIZE_MB")
        return self


settings = Settings()
