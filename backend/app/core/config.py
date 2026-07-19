import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[2]
if os.getenv("SKIP_DOTENV") != "1":
    load_dotenv(BASE_DIR / ".env")


class Settings(BaseModel):
    app_name: str = "AI Interview RAG Coach"
    upload_dir: str = os.getenv("UPLOAD_DIR", "./data/uploads")
    chroma_persist_dir: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
    sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", "./data/app.db")
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
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))
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


settings = Settings()
