from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class Settings(BaseModel):
    app_name: str = "AI Interview RAG Coach"
    upload_dir: str = "./data/uploads"
    chroma_persist_dir: str = "./data/chroma_db"
    sqlite_db_path: str = "./data/app.db"
    embedding_model_name: str = "BAAI/bge-small-zh-v1.5"


settings = Settings()