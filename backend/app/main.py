from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.infrastructure.config import settings
from app.infrastructure.database import Base, engine, session_scope
from app.infrastructure.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        seed_database(session)
    # 启动飞书 WebSocket 事件监听（无凭证 / 未安装 lark_oapi 时自动跳过）
    from app.infrastructure.feishu_events import start_event_listener

    start_event_listener()
    yield


app = FastAPI(
    title="Ontology AI Coding MVP",
    description="本体驱动 AI 软件工程平台的教学型 MVP",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {
        "name": "Ontology AI Coding MVP",
        "docs": "/docs",
        "health": "/api/health",
    }
