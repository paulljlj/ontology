from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.report_routes import router as report_router
from app.infrastructure.config import settings
from app.infrastructure.database import Base, engine, session_scope
from app.infrastructure.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        seed_database(session)
    # 只有显式启用时才加载飞书 SDK，避免无关能力拖慢本地 Goal Runner 冷启动。
    if settings.feishu_event_enabled:
        from app.infrastructure.feishu_events import start_event_listener

        start_event_listener()
    yield


app = FastAPI(
    title="本体智能体工作台",
    description="本体驱动的需求理解、任务编排、推理执行与结果交付平台",
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
app.include_router(report_router, prefix="/api")


@app.get("/")
def root():
    return {
        "name": "本体智能体工作台",
        "docs": "/docs",
        "health": "/api/health",
    }
