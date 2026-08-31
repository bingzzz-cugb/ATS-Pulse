"""
Papers API Router
"""

import json
import re
import urllib.parse
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from arxiv_pulse.core import Config
from arxiv_pulse.models import Paper
from arxiv_pulse.services.figure_service import fetch_and_cache_figure, get_figure_url_cached
from arxiv_pulse.services.paper_service import (
    enhance_paper_data,
    summarize_and_cache_paper,
)
from arxiv_pulse.utils import sse_event, sse_response
from arxiv_pulse.web.dependencies import get_db

router = APIRouter()


def _parse_date_param(v: str | None) -> datetime | None:
    """解析 YYYY-MM-DD 查询参数,失败返回 None(由调用方决定是否报错)"""
    if not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, f"日期格式应为 YYYY-MM-DD: {v}")


def _validate_date_range(date_from: datetime | None, date_to: datetime | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from 不能晚于 date_to")


def _apply_date_range(query, date_from: datetime | None, date_to: datetime | None):
    """按日期区间构造 published 过滤;区间为空时返回原 query"""
    if not date_from and not date_to:
        return query
    conds = []
    if date_from:
        conds.append(Paper.published >= date_from)
    if date_to:
        conds.append(Paper.published < date_to + timedelta(days=1))
    return query.filter(and_(*conds))


def _build_source_cond(source_list: list[str] | None, category_list: list[str] | None = None):
    """按来源构建 SQLAlchemy 过滤条件；doi 期刊按 categories 精确匹配，arXiv 可附领域过滤"""
    from sqlalchemy import and_, or_

    from arxiv_pulse.crawler.publisher import PUBLISHERS

    conds = []
    if source_list and "arxiv" in source_list:
        if category_list:
            cat_conds = []
            for cat in category_list:
                cat_conds.append(Paper.categories.contains(cat))
                cat_conds.append(Paper.primary_category.contains(cat))
            conds.append(and_(Paper.source == "arxiv", or_(*cat_conds)))
        else:
            conds.append(Paper.source == "arxiv")
    if source_list:
        for pub in PUBLISHERS:
            if pub["key"] in source_list:
                conds.append(and_(Paper.source == "doi", Paper.categories == pub["categories"]))
    return or_(*conds) if conds else None


def _paper_matches_source(paper, source_list: list[str] | None) -> bool:
    """纯 Python 判断论文是否属于勾选来源（用于缓存在内存过滤）"""
    if not source_list:
        return True
    if paper.source == "arxiv":
        return "arxiv" in source_list
    if paper.source == "doi":
        from arxiv_pulse.crawler.publisher import PUBLISHERS

        return any(pub["key"] in source_list and paper.categories == pub["categories"]
                   for pub in PUBLISHERS)
    return False


_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")


def looks_like_full_title(q: str) -> bool:
    return len(q) > 15 and " " in q.strip()


def parse_arxiv_id(query: str) -> str | None:
    """Parse arXiv ID from various formats"""
    q = query.strip()
    if q.startswith("arXiv:"):
        q = q[6:]
    arxiv_pattern = r"(\d{4}\.\d{4,5})"
    match = re.search(arxiv_pattern, q)
    return match.group(1) if match else None


@router.get("")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    days: int | None = None,
):
    """List papers with pagination and filters"""
    with get_db().get_session() as session:
        query = session.query(Paper)

        if category:
            query = query.filter(Paper.categories.contains(category) | Paper.primary_category.contains(category))

        if days:
            cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
            query = query.filter(Paper.published >= cutoff)

        total = query.count()
        papers = query.order_by(Paper.published.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "papers": [enhance_paper_data(p) for p in papers],
        }


@router.get("/recent")
async def get_recent_papers(
    days: int = Query(7, ge=1),
    date_from: str | None = Query(None, description="Start date (YYYY-MM-DD), takes precedence over days"),
    date_to: str | None = Query(None, description="End date (YYYY-MM-DD), takes precedence over days"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    categories: str | None = Query(None, description="Comma-separated category codes"),
    sources: str | None = Query(None, description="Comma-separated sources: arxiv,tgrs,science"),
    profile_ids: str | None = Query(None, description="Comma-separated research profile ids"),
):
    """Get recent papers with pagination and optional category/source filter"""
    source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    category_list = [c.strip() for c in categories.split(",")] if categories else None
    profile_list = [int(x) for x in profile_ids.split(",") if x.strip().isdigit()] if profile_ids else None
    date_from = _parse_date_param(date_from)
    date_to = _parse_date_param(date_to)
    _validate_date_range(date_from, date_to)
    with get_db().get_session() as session:
        if date_from or date_to:
            query = _apply_date_range(session.query(Paper), date_from, date_to)
        else:
            cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
            query = session.query(Paper).filter(Paper.published >= cutoff)

        source_cond = _build_source_cond(source_list, category_list)
        if source_cond is not None:
            query = query.filter(source_cond)

        if profile_list:
            from arxiv_pulse.models import PaperProfile

            query = query.join(PaperProfile, PaperProfile.paper_id == Paper.id).filter(
                PaperProfile.profile_id.in_(profile_list)
            )

        total = query.count()
        papers = query.order_by(Paper.published.desc()).offset(offset).limit(limit).all()

        return {
            "days": days,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(papers) < total,
            "papers": [enhance_paper_data(p, session) for p in papers],
        }


@router.get("/recent/cache")
async def get_recent_cache(
    sources: str | None = Query(None, description="Comma-separated sources: arxiv,tgrs,science"),
):
    """Get cached recent papers (instant load)"""
    source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    db = get_db()
    cache = db.get_recent_cache()

    if not cache:
        return {"cached": False, "papers": [], "total": 0}

    paper_ids = cache.get("paper_ids", [])
    if not paper_ids:
        return {
            "cached": True,
            "papers": [],
            "total": 0,
            "days_back": cache.get("days_back", 7),
            "updated_at": cache.get("updated_at"),
        }

    with db.get_session() as session:
        papers = session.query(Paper).filter(Paper.id.in_(paper_ids)).all()
        id_to_paper = {p.id: p for p in papers}
        ordered_papers = [id_to_paper[pid] for pid in paper_ids if pid in id_to_paper]
        ordered_papers = [p for p in ordered_papers if _paper_matches_source(p, source_list)]
        result = [enhance_paper_data(p, session) for p in ordered_papers]

    return {
        "cached": True,
        "papers": result,
        "total": len(ordered_papers),
        "days_back": cache.get("days_back", 7),
        "updated_at": cache.get("updated_at"),
    }


@router.get("/recent/cache/stream")
async def get_recent_cache_stream(
    sources: str | None = Query(None, description="Comma-separated sources: arxiv,tgrs,science"),
):
    """SSE: Get cached recent papers with progress"""
    source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None

    async def event_generator():
        import asyncio

        db = get_db()
        cache = db.get_recent_cache()

        if not cache:
            yield sse_event("done", {"total": 0, "cached": False})
            return

        paper_ids = cache.get("paper_ids", [])
        if not paper_ids:
            yield sse_event("done", {"total": 0, "db_total": 0, "cached": True})
            return

        with db.get_session() as session:
            papers = session.query(Paper).filter(Paper.id.in_(paper_ids)).all()
            id_to_paper = {p.id: p for p in papers}
            ordered = [id_to_paper[pid] for pid in paper_ids if pid in id_to_paper]
            ordered = [p for p in ordered if _paper_matches_source(p, source_list)]

        total = len(ordered)
        db_total = cache.get("total_count", total)

        yield sse_event(
            "start",
            {
                "total": total,
                "db_total": db_total,
                "days_back": cache.get("days_back", 7),
                "updated_at": cache.get("updated_at"),
            },
        )
        await asyncio.sleep(0.01)

        with db.get_session() as session:
            for i, paper in enumerate(ordered, 1):
                enhanced = enhance_paper_data(paper, session)
                yield sse_event("result", {"paper": enhanced, "index": i, "total": total})
                await asyncio.sleep(0.01)

        yield sse_event("done", {"total": total, "db_total": total, "cached": True})

    return sse_response(event_generator)


@router.get("/recent/status")
async def get_recent_cache_status():
    """Get recent papers cache status"""
    db = get_db()
    cache = db.get_recent_cache()

    if not cache:
        return {"has_cache": False, "days_back": 7, "total_count": 0, "updated_at": None}

    return {
        "has_cache": True,
        "days_back": cache.get("days_back", 7),
        "total_count": cache.get("total_count", 0),
        "updated_at": cache.get("updated_at"),
    }


# 活跃的更新任务注册表：task_id -> {"value": True}（被取消标记）
_ACTIVE_UPDATE_TASKS: dict[str, dict] = {}


def _register_update_task(task_id: str) -> dict:
    flag = {"value": False}
    _ACTIVE_UPDATE_TASKS[task_id] = flag
    return flag


def _unregister_update_task(task_id: str) -> None:
    _ACTIVE_UPDATE_TASKS.pop(task_id, None)


@router.post("/recent/update-cancel")
async def cancel_recent_update():
    """标记所有正在运行的近期更新任务取消"""
    for flag in _ACTIVE_UPDATE_TASKS.values():
        flag["value"] = True
    return {"success": True, "cancelled": len(_ACTIVE_UPDATE_TASKS)}


@router.post("/recent/update")
async def update_recent_papers(
    days: int = Query(7, ge=1, le=30),
    date_from: str | None = Query(None, description="Start date (YYYY-MM-DD), takes precedence over days"),
    date_to: str | None = Query(None, description="End date (YYYY-MM-DD), takes precedence over days"),
    need_sync: bool = Query(True),
    categories: str | None = Query(None, description="Comma-separated category codes"),
    sources: str | None = Query(None, description="Comma-separated sources: arxiv,tgrs,science"),
    profile_ids: str | None = Query(None, description="Comma-separated research profile ids"),
    limit: int | None = Query(None, ge=1, le=200, description="Override config limit"),
):
    """SSE endpoint: sync -> query -> cache recent papers"""

    date_from = _parse_date_param(date_from)
    date_to = _parse_date_param(date_to)
    _validate_date_range(date_from, date_to)
    use_range = bool(date_from or date_to)
    date_from_str = date_from.strftime("%Y-%m-%d") if date_from else None
    date_to_str = date_to.strftime("%Y-%m-%d") if date_to else None

    async def event_generator():
        import asyncio
        import uuid

        from arxiv_pulse.models import SyncTask

        db = get_db()
        task_id = str(uuid.uuid4())

        category_list = [c.strip() for c in categories.split(",")] if categories else []
        source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else []
        profile_list = [int(x) for x in profile_ids.split(",") if x.strip().isdigit()] if profile_ids else []
        query_limit = limit or Config.RECENT_PAPERS_LIMIT
        sync_years = Config.YEARS_BACK

        with db.get_session() as session:
            task = SyncTask(id=task_id, task_type="recent_update", status="pending")
            session.add(task)
            session.commit()

        cancelled_flag = _register_update_task(task_id)

        if not source_list and not profile_list:
            _unregister_update_task(task_id)
            yield sse_event("log", {"message": "请选择更新来源"})
            return

        yield sse_event("log", {"message": "开始更新最近论文..."})
        await asyncio.sleep(0.1)

        if use_range:
            range_desc = f"{date_from_str or '最早'} ~ {date_to_str or '今天'}"
            yield sse_event("log", {"message": f"查询范围: {range_desc}"})
        else:
            yield sse_event("log", {"message": f"查询范围: 最近 {days} 天"})
        await asyncio.sleep(0.1)

        if category_list:
            yield sse_event("log", {"message": f"领域过滤: {', '.join(category_list)}"})
            await asyncio.sleep(0.1)

        total_added = 0

        if need_sync and profile_list:
            from arxiv_pulse.models import ResearchProfile
            from arxiv_pulse.services.profile_service import sync_profile_papers

            with db.get_session() as session:
                task = session.query(SyncTask).filter_by(id=task_id).first()
                if task:
                    task.status = "running"
                    task.message = "按档案同步..."
                    session.commit()
                profiles = (
                    session.query(ResearchProfile)
                    .filter(ResearchProfile.id.in_(profile_list), ResearchProfile.enabled == True)
                    .all()
                )
            if not profiles:
                yield sse_event("log", {"message": "所选档案不存在或已停用"})
            for prof in profiles:
                if cancelled_flag["value"]:
                    _unregister_update_task(task_id)
                    yield sse_event("log", {"message": "同步已取消"})
                    return
                yield sse_event("log", {"message": f"开始同步档案: {prof.name}"})
                await asyncio.sleep(0.05)
                try:
                    stats = await asyncio.to_thread(
                        sync_profile_papers, prof, date_from_str, date_to_str,
                        log_cb=lambda msg: None,
                    )
                except Exception as e:
                    yield sse_event("log", {"message": f"档案同步出错: {str(e)[:100]}"})
                    continue
                total_added += stats["total_new"]
                yield sse_event(
                    "log",
                    {
                        "message": f"档案 {prof.name}: arXiv+{stats['arxiv_new']} / 期刊+{stats['crossref_new']} / S2+{stats['s2_new']}，共新增 {stats['total_new']} 篇"
                    },
                )
            yield sse_event("log", {"message": "档案同步完成"})
            await asyncio.sleep(0.05)

        if need_sync and not profile_list:
            with db.get_session() as session:
                task = session.query(SyncTask).filter_by(id=task_id).first()
                if task:
                    task.status = "running"
                    task.message = "正在同步新论文..."
                    session.commit()

            try:
                if "arxiv" in source_list:
                    yield sse_event("log", {"message": "正在同步 arXiv 论文..."})
                    await asyncio.sleep(0.1)

                    from arxiv_pulse.crawler import ArXivCrawler

                    crawler = ArXivCrawler()
                    queries = Config.SEARCH_QUERIES

                    for i, query in enumerate(queries, 1):
                        if cancelled_flag["value"]:
                            _unregister_update_task(task_id)
                            yield sse_event("log", {"message": "同步已取消"})
                            return
                        query_short = query[:50] + "..." if len(query) > 50 else query
                        yield sse_event("log", {"message": f"[{i}/{len(queries)}] 同步: {query_short}"})
                        await asyncio.sleep(0.05)

                        try:
                            result = await asyncio.to_thread(
                                crawler.sync_query,
                                query=query,
                                years_back=sync_years,
                                force=False,
                                date_from=date_from_str,
                                date_to=date_to_str,
                            )
                            total_added += result.get("new_papers", 0)
                        except Exception as e:
                            yield sse_event("log", {"message": f"  同步出错: {str(e)[:80]}"})

                    yield sse_event("log", {"message": f"arXiv 同步完成，新增 {total_added} 篇论文"})
                    await asyncio.sleep(0.1)
                else:
                    yield sse_event("log", {"message": "未勾选 arXiv，跳过 arXiv 同步"})
                    await asyncio.sleep(0.05)

            except Exception as e:
                yield sse_event("log", {"message": f"同步失败: {str(e)[:100]}"})
                await asyncio.sleep(0.05)

            # 同步非 arXiv 期刊（只同步勾选的，支持取消）
            pub_keys = [k for k in source_list if k != "arxiv"]
            if pub_keys:
                try:
                    from arxiv_pulse.crawler.publisher import sync_all_publishers

                    yield sse_event("log", {"message": "同步期刊论文..."})
                    await asyncio.sleep(0.05)
                    pub_result = await asyncio.to_thread(
                        sync_all_publishers, days_back=7, pub_keys=pub_keys,
                        cancel_check=lambda: cancelled_flag["value"],
                        date_from=date_from_str, date_to=date_to_str,
                    )
                    if cancelled_flag["value"]:
                        _unregister_update_task(task_id)
                        yield sse_event("log", {"message": "同步已取消"})
                        return
                    total_added += pub_result.get("new", 0)
                    yield sse_event("log", {"message": f"期刊同步完成，新增 {pub_result.get('new', 0)} 篇"})
                except Exception as e:
                    yield sse_event("log", {"message": f"期刊同步出错: {str(e)[:100]}"})
        else:
            yield sse_event("log", {"message": "跳过同步，直接查询数据库"})
            await asyncio.sleep(0.1)

        yield sse_event("log", {"message": "正在查询最近论文..."})
        await asyncio.sleep(0.1)

        with db.get_session() as session:
            if use_range:
                query = _apply_date_range(session.query(Paper), date_from, date_to)
            else:
                cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
                query = session.query(Paper).filter(Paper.published >= cutoff)

            source_cond = _build_source_cond(source_list, category_list)
            if source_cond is not None:
                query = query.filter(source_cond)

            total_count = query.count()
            papers = query.order_by(Paper.published.desc()).limit(query_limit).all()
            paper_ids = [p.id for p in papers]

        yield sse_event("log", {"message": f"找到 {total_count} 篇论文，加载前 {len(papers)} 篇"})
        await asyncio.sleep(0.1)

        summarized_count = 0
        figure_count = 0

        for i, paper in enumerate(papers):
            if cancelled_flag["value"]:
                _unregister_update_task(task_id)
                yield sse_event("log", {"message": "更新已取消"})
                return
            if not paper.summarized:
                yield sse_event("log", {"message": f"[{i + 1}/{len(papers)}] 总结论文 {paper.arxiv_id}..."})
                await asyncio.sleep(0.05)
                if summarize_and_cache_paper(paper):
                    summarized_count += 1
                    with db.get_session() as s:
                        refreshed = s.query(Paper).filter_by(arxiv_id=paper.arxiv_id).first()
                        if refreshed:
                            paper = refreshed

            with db.get_session() as s:
                figure_url = get_figure_url_cached(paper.arxiv_id, s)
            if not figure_url:
                yield sse_event("log", {"message": f"[{i + 1}/{len(papers)}] 获取图片 {paper.arxiv_id}..."})
                await asyncio.sleep(0.05)
                fetch_and_cache_figure(paper.arxiv_id)
                figure_count += 1

            enhanced = enhance_paper_data(paper)
            yield sse_event("result", {"paper": enhanced, "index": i + 1, "total": len(papers)})
            await asyncio.sleep(0.03)

        with db.get_session() as session:
            task = session.query(SyncTask).filter_by(id=task_id).first()
            if task:
                task.status = "completed"
                task.progress = 100
                task.message = "更新完成"
                task.result = json.dumps({"total_papers": len(papers), "new_synced": total_added})
                task.completed_at = datetime.now(UTC).replace(tzinfo=None)
                session.commit()

        # 全部处理完成后才写缓存——取消时会提前 return，不会留下过期缓存。
        # 自定义日期区间不写缓存(缓存仅表达"最近 N 天"语义)
        if not use_range:
            db.set_recent_cache(days_back=days, paper_ids=paper_ids, total_count=total_count)
            yield sse_event("log", {"message": "缓存已更新"})
            await asyncio.sleep(0.1)

        yield sse_event(
            "done",
            {
                "total": total_count,
                "loaded": len(papers),
                "synced": total_added,
                "summarized": summarized_count,
                "figures": figure_count,
            },
        )

        _unregister_update_task(task_id)

    return sse_response(event_generator)


@router.get("/quick")
async def quick_fetch(q: str = Query(..., min_length=1)):
    """SSE endpoint for quick paper fetch by arXiv ID or fuzzy search"""

    async def event_generator():
        import asyncio

        from arxiv_pulse.crawler import ArXivCrawler

        db = get_db()
        arxiv_id = parse_arxiv_id(q)

        if arxiv_id:
            yield sse_event("log", {"message": f"识别为 arXiv ID: {arxiv_id}"})
            await asyncio.sleep(0.1)

            with db.get_session() as session:
                paper = session.query(Paper).filter_by(arxiv_id=arxiv_id).first()

            if paper:
                yield sse_event("log", {"message": "在数据库中找到论文"})
                await asyncio.sleep(0.1)

                if not paper.summarized:
                    yield sse_event("log", {"message": "正在生成 AI 总结..."})
                    await asyncio.sleep(0.1)
                    if summarize_and_cache_paper(paper):
                        with db.get_session() as s:
                            s.query(Paper).filter_by(id=paper.id).update({"summarized": True})
                            paper = s.query(Paper).filter_by(arxiv_id=arxiv_id).first()

                with db.get_session() as s:
                    figure_url = get_figure_url_cached(arxiv_id, s)
                    paper = s.query(Paper).filter_by(arxiv_id=arxiv_id).first() or paper
                if not figure_url:
                    yield sse_event("log", {"message": "正在获取论文图片..."})
                    await asyncio.sleep(0.1)
                    fetch_and_cache_figure(arxiv_id)

                enhanced = enhance_paper_data(paper)
                yield sse_event("result", {"paper": enhanced, "match_type": "exact"})
                await asyncio.sleep(0.1)
                yield sse_event("done", {"total": 1})
                return

            yield sse_event("log", {"message": "数据库中无此论文，正在从 arXiv 获取..."})
            await asyncio.sleep(0.1)

            import arxiv as arxiv_lib

            try:
                crawler = ArXivCrawler()
                paper = crawler.fetch_paper_by_id(arxiv_id)

                if paper:
                    yield sse_event("log", {"message": "成功获取论文"})
                    await asyncio.sleep(0.1)

                    yield sse_event("log", {"message": "正在生成 AI 总结..."})
                    await asyncio.sleep(0.1)
                    summarize_and_cache_paper(paper)

                    yield sse_event("log", {"message": "正在获取论文图片..."})
                    await asyncio.sleep(0.1)
                    fetch_and_cache_figure(arxiv_id)

                    with db.get_session() as session:
                        paper = session.query(Paper).filter_by(arxiv_id=arxiv_id).first()
                    enhanced = enhance_paper_data(paper)
                    yield sse_event("result", {"paper": enhanced, "match_type": "exact"})
                    await asyncio.sleep(0.1)
                    yield sse_event("done", {"total": 1})
                    return
                else:
                    yield sse_event(
                        "error", {"message": f"未找到论文: {arxiv_id}（可能是 arXiv API 暂时不可用，请稍后重试）"}
                    )
                    return

            except arxiv_lib.HTTPError as e:
                yield sse_event("error", {"message": f"arXiv API 请求失败 (HTTP {e.status}): 请稍后重试"})
                return
            except Exception as e:
                yield sse_event("error", {"message": f"获取失败: {str(e)[:100]}"})
                return

        yield sse_event("log", {"message": "正在搜索本地数据库..."})
        await asyncio.sleep(0.05)

        from arxiv_pulse.search import SearchEngine, SearchFilter

        with db.get_session() as session:
            search_engine = SearchEngine(session)
            filter_config = SearchFilter(
                query=q,
                search_fields=["title", "abstract", "authors"],
                days_back=0,
                limit=Config.SEARCH_LIMIT,
                sort_by="published",
                sort_order="desc",
            )
            local_papers = search_engine.search_papers(filter_config)

        if local_papers:
            for p in local_papers[:20]:
                with db.get_session() as s:
                    fresh = s.query(Paper).filter_by(id=p.id).first()
                if fresh:
                    p = fresh
                yield sse_event("result", {"paper": enhance_paper_data(p), "match_type": "local"})
            yield sse_event("done", {"total": len(local_papers)})
            return

        yield sse_event("log", {"message": "本地未命中，尝试按 DOI / 标题远程检索..."})
        await asyncio.sleep(0.05)

        q_stripped = q.strip()
        # 本地精确匹配（arXiv ID / DOI）
        with db.get_session() as s2:
            local_exact = s2.query(Paper).filter(
                (Paper.arxiv_id == q_stripped) | (Paper.doi == q_stripped.lower()) | (Paper.arxiv_id == q_stripped.lower())
            ).first()
        if local_exact:
            yield sse_event("result", {"paper": enhance_paper_data(local_exact), "match_type": "exact"})
            yield sse_event("done", {"total": 1})
            return


        if _DOI_RE.match(q_stripped):
            import urllib.request as urllib_req

            from arxiv_pulse.crawler.publisher import save_doi_paper

            doi_l = q_stripped.lower()
            try:
                req = urllib_req.Request(
                    f"https://api.crossref.org/works/{urllib.parse.quote(doi_l)}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib_req.urlopen(req, timeout=20) as resp:
                    item = json.loads(resp.read().decode("utf-8"))["message"]
                container = item.get("container-title") or [""]
                container = container[0] if isinstance(container, list) else container
                pub = {"key": "custom", "name": container or "Journal", "categories": container or "Journal"}
                save_doi_paper(item, pub, db=db)
            except Exception as e:
                yield sse_event("error", {"message": f"DOI 检索失败: {str(e)[:80]}"})
                return
            with db.get_session() as s:
                paper = s.query(Paper).filter_by(arxiv_id=doi_l).first()
            if paper:
                yield sse_event("log", {"message": "已从 Crossref 获取论文"})
                yield sse_event("result", {"paper": enhance_paper_data(paper), "match_type": "doi"})
                yield sse_event("done", {"total": 1})
            else:
                yield sse_event("error", {"message": "DOI 已存在记录或入库失败"})
            return

        if looks_like_full_title(q_stripped):
            yield sse_event("log", {"message": "正按标题检索 arXiv..."})
            try:
                crawler = ArXivCrawler()
                papers, total, new_count = crawler.search_and_save(f'ti:"{q_stripped}"', max_results=5)
            except Exception as e:
                papers, total, new_count = [], 0, 0
                yield sse_event("log", {"message": f"arXiv 标题检索失败: {str(e)[:50]}"})
            if papers:
                for p in papers[:5]:
                    yield sse_event("result", {"paper": enhance_paper_data(p), "match_type": "title"})
                yield sse_event("done", {"total": len(papers)})
                return
            yield sse_event("log", {"message": "arXiv 未命中，尝试 Crossref..."})
            try:
                import urllib.request as urllib_req

                from arxiv_pulse.crawler.publisher import save_doi_paper

                url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
                    {"query.bibliographic": q_stripped, "rows": "5", "mailto": "arxiv-pulse@example.com",
                     "select": "DOI,title,author,abstract,container-title,published"}
                )
                req = urllib_req.Request(url, headers={"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"})
                with urllib_req.urlopen(req, timeout=20) as resp:
                    items = json.loads(resp.read().decode("utf-8"))["message"].get("items", [])
                for item in items[:5]:
                    pub = {"key": "custom", "name": "Journal",
                           "categories": (item.get("container-title") or [""])[0] if item.get("container-title") else "Journal"}
                    save_doi_paper(item, pub, db=db)
                with db.get_session() as s:
                    for item in items[:5]:
                        doi_l = (item.get("DOI") or "").lower()
                        paper = s.query(Paper).filter_by(arxiv_id=doi_l).first()
                        if paper:
                            yield sse_event("result", {"paper": enhance_paper_data(paper), "match_type": "title"})
                yield sse_event("done", {"total": 5})
            except Exception as e:
                yield sse_event("error", {"message": f"Crossref 检索失败: {str(e)[:80]}"})
            return

        yield sse_event("log", {"message": "未识别为特定文章，未在本地找到相关论文"})
        yield sse_event("done", {"total": 0})

    return sse_response(event_generator)


@router.get("/search")
async def search_papers(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    days: int | None = None,
):
    """Search papers by query (basic search without AI parsing)"""
    from arxiv_pulse.search import SearchEngine, SearchFilter

    with get_db().get_session() as session:
        search_engine = SearchEngine(session)
        days_back = days if days else 0

        filter_config = SearchFilter(
            query=q,
            search_fields=["title", "abstract"],
            days_back=days_back,
            limit=page_size * 2,
            sort_by="published",
            sort_order="desc",
        )

        papers = search_engine.search_papers(filter_config)

        return {
            "query": q,
            "total": len(papers),
            "page": page,
            "page_size": page_size,
            "papers": [enhance_paper_data(p) for p in papers[:page_size]],
        }


@router.get("/search/stream")
async def search_papers_stream(
    q: str = Query(..., min_length=1),
    days: int | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    """SSE endpoint for real-time search with AI parsing and logs"""

    async def event_generator():
        import asyncio

        yield sse_event("log", {"message": f"正在搜索: '{q}'"})
        await asyncio.sleep(0.1)

        search_terms = [q]

        if Config.AI_API_KEY:
            try:
                import openai

                yield sse_event("log", {"message": "正在使用 AI 解析搜索词..."})
                await asyncio.sleep(0.1)

                client = openai.OpenAI(api_key=Config.AI_API_KEY, base_url=Config.AI_BASE_URL)

                ai_prompt = f"""
用户正在搜索arXiv物理/计算材料科学论文，查询是: "{q}"

请将自然语言查询转换为适合arXiv搜索的关键词或短语。

重要规则：
1. 如果查询已经是明确的搜索词（如"DeepH"、"deep learning Hamiltonian"、"DFT计算"），直接使用它，不要添加同义词
2. 如果查询包含专业术语、缩写或专有名词，保持原样作为主要搜索词
3. 仅当查询非常模糊或一般性时，才生成1-2个相关关键词
4. 优先保持查询的原始意图，不要添加不相关的关键词
5. 对于英文查询，保持原样；对于中文查询，翻译为英文关键词

返回格式：JSON数组，包含1-2个搜索关键词/短语。
只返回JSON数组，不要其他文本。
"""

                response = client.chat.completions.create(
                    model=Config.AI_MODEL or "DeepSeek-V3.2",
                    messages=[
                        {
                            "role": "system",
                            "content": "你是arXiv论文搜索助手，擅长识别专业术语并将自然语言查询转换为学术搜索关键词。",
                        },
                        {"role": "user", "content": ai_prompt},
                    ],
                    max_tokens=200,
                    temperature=0.3,
                )

                ai_response = response.choices[0].message.content
                if ai_response:
                    try:
                        parsed = json.loads(ai_response)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            search_terms = parsed
                            yield sse_event("ai_parsed", {"terms": search_terms})
                            await asyncio.sleep(0.1)
                    except:
                        pass

            except Exception as e:
                yield sse_event("log", {"message": f"AI 解析失败: {str(e)[:100]}"})
                await asyncio.sleep(0.1)

        yield sse_event("log", {"message": f"搜索词: {', '.join(search_terms)}"})
        await asyncio.sleep(0.1)

        yield sse_event("log", {"message": "正在数据库中搜索..."})
        await asyncio.sleep(0.1)

        from arxiv_pulse.search import SearchEngine, SearchFilter

        with get_db().get_session() as session:
            search_engine = SearchEngine(session)
            days_back = days if days else 0

            all_papers = []
            for term in search_terms:
                filter_config = SearchFilter(
                    query=term,
                    search_fields=["title", "abstract"],
                    days_back=days_back,
                    limit=limit * 2,
                    sort_by="published",
                    sort_order="desc",
                )
                papers = search_engine.search_papers(filter_config)
                all_papers.extend(papers)

            seen_ids = set()
            unique_papers = []
            for p in all_papers:
                if p.arxiv_id not in seen_ids:
                    seen_ids.add(p.arxiv_id)
                    unique_papers.append(p)

            unique_papers.sort(key=lambda p: p.published if p.published else datetime.min, reverse=True)
            unique_papers = unique_papers[:limit]

        yield sse_event("log", {"message": f"找到 {len(unique_papers)} 篇论文"})
        await asyncio.sleep(0.1)

        db = get_db()
        summarized_count = 0
        figure_count = 0

        for i, paper in enumerate(unique_papers):
            with db.get_session() as s:
                fresh_paper = s.query(Paper).filter_by(arxiv_id=paper.arxiv_id).first()
                if fresh_paper:
                    paper = fresh_paper

            if not paper.summarized:
                yield sse_event("log", {"message": f"[{i + 1}/{len(unique_papers)}] 总结论文 {paper.arxiv_id}..."})
                await asyncio.sleep(0.05)
                if summarize_and_cache_paper(paper):
                    summarized_count += 1
                    with db.get_session() as s:
                        refreshed = s.query(Paper).filter_by(arxiv_id=paper.arxiv_id).first()
                        if refreshed:
                            paper = refreshed

            with db.get_session() as s:
                figure_url = get_figure_url_cached(paper.arxiv_id, s)
            if not figure_url:
                yield sse_event("log", {"message": f"[{i + 1}/{len(unique_papers)}] 获取图片 {paper.arxiv_id}..."})
                await asyncio.sleep(0.05)
                fetch_and_cache_figure(paper.arxiv_id)
                figure_count += 1

            enhanced = enhance_paper_data(paper)
            yield sse_event("result", {"paper": enhanced, "index": i + 1, "total": len(unique_papers)})
            await asyncio.sleep(0.05)

        yield sse_event("done", {"total": len(unique_papers), "summarized": summarized_count, "figures": figure_count})

    return sse_response(event_generator)


class AIFilterPapersRequest(BaseModel):
    query: str
    paper_ids: list[int]


@router.post("/ai-filter")
async def ai_filter_papers(data: AIFilterPapersRequest):
    """AI-powered filter papers from a given list by query"""
    if not data.paper_ids:
        return {"papers": [], "total_found": 0}

    with get_db().get_session() as session:
        papers = session.query(Paper).filter(Paper.id.in_(data.paper_ids)).all()

        if not papers:
            return {"papers": [], "total_found": 0}

        papers_info = []
        for idx, paper in enumerate(papers):
            papers_info.append(
                {
                    "index": idx,
                    "id": paper.id,
                    "title": paper.title or "",
                    "arxiv_id": paper.arxiv_id,
                }
            )

        titles_text = "\n".join([f"{p['index']}. {p['title']}" for p in papers_info])

        prompt = f"""用户描述：{data.query}

以下是论文列表的标题（每行一个）：
{titles_text}

请找出与用户描述最相关的论文，返回编号列表（JSON数组格式），如：[1, 3, 5]

如果没有相关论文，返回空列表 []
只返回JSON数组，不要其他文字。"""

        try:
            import openai

            client = openai.OpenAI(api_key=Config.AI_API_KEY, base_url=Config.AI_BASE_URL)

            response = client.chat.completions.create(
                model=Config.AI_MODEL or "DeepSeek-V3.2",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
            )

            result_text = response.choices[0].message.content.strip()

            import re

            match = re.search(r"\[.*?\]", result_text)
            if match:
                indices = json.loads(match.group())
            else:
                indices = []

            matched_papers = []
            for p in papers_info:
                if p["index"] in indices:
                    paper = session.query(Paper).filter_by(id=p["id"]).first()
                    if paper:
                        paper_data = enhance_paper_data(paper)
                        paper_data["_originalIndex"] = p["index"]
                        matched_papers.append(paper_data)

            return {"papers": matched_papers, "total_found": len(matched_papers)}

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI filter failed: {str(e)[:100]}")


@router.get("/{paper_id}")
async def get_paper(paper_id: int):
    """Get paper by ID with enhanced data"""
    with get_db().get_session() as session:
        paper = session.query(Paper).filter_by(id=paper_id).first()
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        return enhance_paper_data(paper)


@router.get("/{paper_id}/translate")
async def get_paper_translation(paper_id: int):
    """Get paper translation (title and abstract)"""
    from arxiv_pulse.services.translation_service import translate_text

    with get_db().get_session() as session:
        paper = session.query(Paper).filter_by(id=paper_id).first()
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        return {
            "id": paper.id,
            "arxiv_id": paper.arxiv_id,
            "title": paper.title,
            "title_translation": translate_text(paper.title, Config.TRANSLATE_LANGUAGE),
            "abstract": paper.abstract,
            "abstract_translation": translate_text(paper.abstract, Config.TRANSLATE_LANGUAGE) if paper.abstract else "",
        }


@router.get("/arxiv/{arxiv_id}")
async def get_paper_by_arxiv_id(arxiv_id: str):
    """Get paper by arXiv ID with enhanced data"""
    with get_db().get_session() as session:
        paper = session.query(Paper).filter_by(arxiv_id=arxiv_id).first()
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        return enhance_paper_data(paper)


@router.get("/pdf/{arxiv_id}")
async def download_pdf(arxiv_id: str):
    """Download PDF from arXiv (proxy to avoid CORS)"""
    import requests
    from fastapi.responses import Response

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    try:
        response = requests.get(pdf_url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200:
            return Response(
                content=response.content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{arxiv_id}.pdf"'},
            )
        else:
            raise HTTPException(status_code=response.status_code, detail="Failed to download PDF from arXiv")
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to download PDF: {str(e)}")


@router.get("/{arxiv_id}/pdf")
async def get_paper_pdf(arxiv_id: str):
    """获取论文 PDF（arxiv 源本地缓存；doi 源跳转外部链接）"""
    from fastapi.responses import FileResponse, RedirectResponse, Response

    from arxiv_pulse.services.pdf_service import get_or_download_arxiv_pdf, pdf_cache_path

    with get_db().get_session() as session:
        paper = session.query(Paper).filter_by(arxiv_id=arxiv_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    cache = pdf_cache_path(arxiv_id)
    if cache.exists():
        return FileResponse(
            cache,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline"},
        )

    if paper.source == "doi":
        if paper.pdf_url:
            return RedirectResponse(paper.pdf_url, status_code=302)
        raise HTTPException(status_code=404, detail="No PDF URL available")

    data = get_or_download_arxiv_pdf(arxiv_id)
    if data is None:
        raise HTTPException(status_code=502, detail="PDF download failed")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )
