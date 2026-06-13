from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.db.database import init_db
from app.api.files import router as files_router
from app.api.knowledge import router as knowledge_router
from app.api.llm import router as llm_router
from app.api.chat import router as chat_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Interview RAG Coach API",
    description="Backend API for AI Interview RAG Coach",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(files_router, prefix="/api", tags=["files"])
app.include_router(knowledge_router, prefix="/api", tags=["知识库"])
app.include_router(llm_router, prefix="/api", tags=["大模型"])
app.include_router(chat_router, prefix="/api", tags=["RAG 问答"])