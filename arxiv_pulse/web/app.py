"""
FastAPI Application Entry Point
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, inspect, text

from arxiv_pulse.__version__ import __version__
from arxiv_pulse.core import Database
from arxiv_pulse.models import Base
from arxiv_pulse.web.api import cache, chat, collections, config, export, papers, stats, tasks

logger = logging.getLogger(__name__)


def _migrate_catalog(engine) -> None:
    """crossref_journals 旧表缺 quartile/sjr 列（SQLite create_all 不改旧表）；
    旧版全量清单（>3 万条）直接清空，首次搜索时按 SJR 二区以上清单自动重新导入"""
    try:
        inspector = inspect(engine)
        if "crossref_journals" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("crossref_journals")}
        with engine.begin() as conn:
            if "quartile" not in cols:
                conn.execute(text("ALTER TABLE crossref_journals ADD COLUMN quartile VARCHAR(4)"))
            if "sjr" not in cols:
                conn.execute(text("ALTER TABLE crossref_journals ADD COLUMN sjr FLOAT"))
            row_count = conn.execute(text("SELECT COUNT(*) FROM crossref_journals")).scalar() or 0
            if row_count > 30000:
                conn.execute(text("DELETE FROM crossref_journals"))
                logger.info("检测到旧版期刊全量清单（%d 条），已清空待重导", row_count)
    except Exception:
        logger.exception("crossref_journals 表迁移失败")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager"""
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/arxiv_papers.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    _migrate_catalog(engine)
    db = Database(db_url)
    db.init_default_config()
    yield


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    app = FastAPI(
        title="arXiv Pulse",
        description="Intelligent arXiv literature crawler and analyzer",
        version=__version__,
        lifespan=lifespan,
    )

    api_router = APIRouter()
    api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
    api_router.include_router(collections.router, prefix="/collections", tags=["collections"])
    api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
    api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
    api_router.include_router(export.router, prefix="/export", tags=["export"])
    api_router.include_router(config.router, prefix="/config", tags=["config"])
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
    api_router.include_router(cache.router, tags=["cache"])

    app.include_router(api_router, prefix="/api")

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": __version__}

    static_path = Path(__file__).parent / "static"
    if static_path.exists() and any(static_path.iterdir()):
        app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")

    @app.middleware("http")
    async def no_cache_static_files(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


app = create_app()
