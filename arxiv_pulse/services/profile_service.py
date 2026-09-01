"""
Profile service - 领域档案 AI 规范化与多源同步
"""

import json
import logging
import re

from arxiv_pulse.core import Config
from arxiv_pulse.crawler.publisher import PUBLISHERS

logger = logging.getLogger(__name__)


def default_journals() -> list[dict]:
    return [{"key": p["key"], "name": p["name"], "issn": p["issn"], "enabled": True} for p in PUBLISHERS]


def generate_retrieval_plan(description: str) -> dict:
    """AI 将自然语言描述规范化为检索计划；失败时降级为原样查询"""
    fallback = {
        "arxiv_queries": [description.strip()],
        "s2_query": description.strip(),
        "keywords": [],
        "exclude_words": [],
    }
    if not Config.AI_API_KEY:
        return fallback
    try:
        import openai

        client = openai.OpenAI(api_key=Config.AI_API_KEY, base_url=Config.AI_BASE_URL)
        resp = client.chat.completions.create(
            model=Config.AI_MODEL or "DeepSeek-V3.2",
            messages=[
                {
                    "role": "system",
                    "content": "你是学术检索规划器。把用户的自然语言检索需求转换为多源检索计划。只输出 JSON，不要 markdown。",
                },
                {
                    "role": "user",
                    "content": (
                        f'用户检索领域描述: "{description}"\n\n'
                        "请输出 JSON：\n"
                        "{"
                        '"arxiv_queries": ["2-3 条 arXiv 高级查询串，使用 AND/OR/引号，如 (ti:"remote sensing" AND ti:"methane")"], '
                        '"s2_query": "Semantic Scholar 关键词串，如 methane remote sensing deep learning", '
                        '"keywords": ["6-10 个英文检索关键词"], '
                        '"exclude_words": ["1-3 个排除词"], '
                        '"suggested_journals": ["候选期刊建议，如 IEEE TGRS"]\n}'
                        "候选期刊：IEEE TGRS、Science、Remote Sensing、JSTARS、ISPRS、GRSL。"
                    ),
                },
            ],
            max_tokens=1500,
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        queries = [q for q in data.get("arxiv_queries", []) if isinstance(q, str) and q.strip()]
        return {
            "arxiv_queries": queries or fallback["arxiv_queries"],
            "s2_query": data.get("s2_query") or fallback["s2_query"],
            "keywords": data.get("keywords", []),
            "exclude_words": data.get("exclude_words", []),
        }
    except Exception as e:
        logger.warning("AI plan 生成失败，使用降级方案: %s", str(e)[:80])
        return fallback


def attach_profile(db, paper, profile_id: int) -> None:
    """给论文打上档案关联（已存在则跳过）"""
    from arxiv_pulse.models import PaperProfile

    if not paper:
        return
    with db.get_session() as session:
        exists = session.query(PaperProfile).filter_by(profile_id=profile_id, paper_id=paper.id).first()
        if not exists:
            session.add(PaperProfile(profile_id=profile_id, paper_id=paper.id))
            session.commit()


def _clean_title(title) -> str:
    if not title:
        return ""
    text = title[0] if isinstance(title, list) else title
    return re.sub(r"<[^>]+>", "", text)


# 期刊过滤停用词：主题判别力过弱的高频词元踢掉，否则过滤形同虚设
_JOURNAL_STOP_TERMS = {
    "remote", "sensing", "satellite", "image", "images", "imagery", "data",
    "model", "models", "based", "using", "analysis", "results", "result",
    "method", "methods", "mapping", "map", "maps", "assessment", "monitoring",
    "algorithm", "algorithms", "new", "study", "paper", "the", "and", "are",
    "of", "in", "to", "a", "an", "on", "by", "with", "from", "for", "use",
    "used", "retrieval", "estimation", "object", "land", "surface", "water",
    "climate", "forest", "few", "mechanism",
}


def _journal_filter_terms(plan: dict, s2_query: str) -> list[str]:
    """从检索计划提取期刊论文的关键词过滤词元（无配置则返回空 = 不过滤）"""
    raw = plan.get("keywords") or []
    source_strs = list(raw) if raw else (s2_query.split() if s2_query else [])
    terms = set()
    for s in source_strs:
        for t in re.split(r"[^a-zA-Z0-9]+", str(s).lower()):
            if len(t) < 3 or t in _JOURNAL_STOP_TERMS:
                continue
            terms.add(t)
    return sorted(terms)


def _paper_origin(paper) -> str:
    """识别论文来自哪个检索来源（S2 收录项带 s2: 前缀搜索标记）"""
    if (paper.search_query or "").startswith("s2:"):
        return "s2"
    if paper.source == "arxiv":
        return "arxiv"
    return "crossref"


def _reconcile_source_links(db, profile, sources: dict, log_cb) -> None:
    """来源被关闭的档案：解除该来源论文与档案的关联（论文保留，视图即来源开关状态）"""
    if sources.get("arxiv", True) and sources.get("crossref", True) and sources.get("s2", True):
        return
    from arxiv_pulse.models import Paper, PaperProfile

    try:
        with db.get_session() as session:
            links = (
                session.query(Paper, PaperProfile)
                .join(PaperProfile, PaperProfile.paper_id == Paper.id)
                .filter(PaperProfile.profile_id == profile.id)
                .all()
            )
            remove_ids = [link.id for paper, link in links if not sources.get(_paper_origin(paper), True)]
            if remove_ids:
                session.query(PaperProfile).filter(PaperProfile.id.in_(remove_ids)).delete(
                    synchronize_session=False
                )
                session.commit()
                log_cb(f"来源对账: 解除 {len(remove_ids)} 篇已关闭来源论文的档案关联")
    except Exception:
        logger.exception("来源关联整理失败")


def _attach_existing_by_doi(db, doi, profile_id) -> None:
    """已入库（如先前全局同步入库）的期刊论文补挂档案关联"""
    from arxiv_pulse.models import Paper

    with db.get_session() as session:
        paper = session.query(Paper).filter(Paper.doi == doi).first()
        if paper:
            attach_profile(db, paper, profile_id)


def sync_profile_papers(profile, date_from=None, date_to=None, source_override=None, log_cb=lambda msg: None) -> dict:
    """按档案三源检索指定区间论文并入库，返回各源统计"""
    from arxiv_pulse.core import Database
    from arxiv_pulse.crawler import ArXivCrawler
    from arxiv_pulse.crawler.arxiv import _date_range_query
    from arxiv_pulse.crawler.publisher import fetch_crossref_items, save_doi_paper

    db = Database()
    plan = {}
    try:
        plan = json.loads(profile.retrieval_plan) if profile.retrieval_plan else {}
    except (ValueError, TypeError):
        pass
    arxiv_queries = [q for q in plan.get("arxiv_queries", []) if q] or [profile.description]
    s2_query = plan.get("s2_query") or profile.description or ""
    exclude_words = [w.lower() for w in plan.get("exclude_words", [])]

    sources = dict(profile.sources_json())
    if source_override:
        sources.update(source_override)

    _reconcile_source_links(db, profile, sources, log_cb)

    result = {"profile": profile.name, "arxiv_new": 0, "crossref_new": 0, "s2_new": 0, "total_new": 0, "found": 0}

    if sources.get("arxiv", True):
        crawler = ArXivCrawler()
        for query in arxiv_queries[:3]:
            q = _date_range_query(query, date_from, date_to) if (date_from or date_to) else query
            try:
                papers, total, new_count = crawler.search_and_save(q, max_results=30)
            except Exception as e:
                log_cb(f"arXiv 查询失败: {query[:40]} ({str(e)[:50]})")
                continue
            result["arxiv_new"] += new_count
            result["found"] += total
            log_cb(f"arXiv: {query[:50]} → 命中 {total}，新增 {new_count}")
            for p in papers:
                attach_profile(db, p, profile.id)

    journals = []
    try:
        journals = [j for j in json.loads(profile.journals) if j.get("enabled")] if profile.journals else []
    except (ValueError, TypeError):
        pass

    if sources.get("crossref", True):
        from arxiv_pulse.crawler.openalex import _uninvert_abstract, save_openalex_item, search_openalex_items

        filter_terms = _journal_filter_terms(plan, s2_query)
        for pub in journals:
            items = search_openalex_items(
                pub["issn"], date_from=date_from, date_to=date_to, rows=200, log_cb=log_cb
            )
            saved = 0
            skipped = 0
            for item in items:
                doi = (item.get("doi") or "").lower().replace("https://doi.org/", "")
                if not doi:
                    continue
                title = (item.get("title") or "").lower()
                abstract = _uninvert_abstract(item.get("abstract_inverted_index")).lower()
                if exclude_words and any(w and w in title for w in exclude_words):
                    continue
                if filter_terms:
                    # 关键词包含过滤：标题或摘要命中任一词元才算该档案主题的文章
                    text = title + " " + abstract
                    if not any(re.search(rf"\b{re.escape(t)}\b", text) for t in filter_terms):
                        skipped += 1
                        continue
                if db.paper_exists(doi):
                    # 已入库的期刊论文补挂档案关联（save_ 内部已做 attach，这里仅处理计数语义）
                    _attach_existing_by_doi(db, doi, profile.id)
                    continue
                saved_paper = save_openalex_item(db, item, pub, profile_id=profile.id)
                if saved_paper is not None:
                    saved += 1
            if saved or skipped:
                log_cb(f"期刊 {pub.get('name', pub['key'])[:30]}: 新增 {saved} 篇，关键词过滤 {skipped} 篇")
            result["crossref_new"] += saved
            result["found"] += len(items)

    if sources.get("s2", True) and s2_query:
        from arxiv_pulse.crawler.s2 import save_s2_item, search_s2_items

        s2_new = 0
        for item in search_s2_items(s2_query, date_from, date_to, api_key=Config.S2_API_KEY, log_cb=log_cb):
            if exclude_words and any(w and w in str(item.get("title") or "").lower() for w in exclude_words):
                continue
            paper = save_s2_item(db, item, profile.id)
            if paper is not None:
                s2_new += 1
        result["s2_new"] = s2_new
        log_cb(f"S2: 新增 {s2_new} 篇")

    result["total_new"] = result["arxiv_new"] + result["crossref_new"] + result["s2_new"]
    return result
