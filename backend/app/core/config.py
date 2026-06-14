import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[2]
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

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    )
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")


settings = Settings()