"""
OpenAlex 检索器 - 期刊论文数据源（publication_date 准确标注，替代 Crossref deposit 口径）

OpenAlex 的 publication_date 是正式发布日期，created_date 是收录日期，
两者分离，避免 Crossref 批量回溯补录导致 deposit 日期混乱的问题。
"""

import json
import logging
import re
import urllib.parse
from datetime import UTC, datetime

from arxiv_pulse.crawler.publisher import _http_get_json

logger = logging.getLogger(__name__)

_OA_WORKS_URL = "https://api.openalex.org/works"
_OA_HEADERS = {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}


def _date_range(date_from: str | None, date_to: str | None) -> str:
    parts = []
    if date_from:
        parts.append(f"from_publication_date:{date_from}")
    if date_to:
        parts.append(f"to_publication_date:{date_to}")
    return ",".join(parts)


def _url(params: dict) -> str:
    return f"{_OA_WORKS_URL}?{urllib.parse.urlencode(params)}"


def search_openalex_items(
    issn: str,
    date_from: str | None = None,
    date_to: str | None = None,
    rows: int = 100,
    max_pages: int = 5,
    log_cb=None,
) -> list[dict]:
    """按 ISSN + publication_date 窗口搜索 OpenAlex 期刊论文

    date_from/date_to 均缺省时返回空（必须明确日期窗口，OpenAlex 全量不可行）
    """
    date_filter = _date_range(date_from, date_to)
    if not date_filter:
        return []

    items: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "filter": f"primary_location.source.issn:{issn},{date_filter}",
            "sort": "publication_date:asc",
            "per-page": str(min(rows, 200)),
            "page": str(page),
            "select": "id,doi,title,publication_date,type,authorships,abstract_inverted_index,primary_location,best_oa_location",
        }
        data = _http_get_json(_url(params), _OA_HEADERS, timeout=30)
        if data is None:
            if log_cb:
                log_cb(f"OpenAlex 请求失败（{issn[:10]} 第 {page} 页）")
            break
        page_items = data.get("results", [])
        items.extend(page_items)
        n_pages = data.get("meta", {}).get("count", 0) / max(1, min(rows, 200))
        if len(page_items) == 0 or page >= int(n_pages) and len(page_items) < min(rows, 200):
            break
        if len(page_items) < min(rows, 200):
            break
    return items


def search_openalex_title(title: str, rows: int = 5, log_cb=None) -> list[dict]:
    """按标题在 OpenAlex 全库搜索（search= 全字段相关性排序），返回最相似的记录"""
    if not title.strip():
        return []
    params = {
        "search": title,
        "per-page": str(min(rows, 20)),
        "select": "id,doi,title,publication_date,type,authorships,abstract_inverted_index,primary_location,best_oa_location",
    }
    data = _http_get_json(_url(params), _OA_HEADERS, timeout=30)
    if data is None:
        if log_cb:
            log_cb("OpenAlex 标题搜索失败")
        return []
    return data.get("results", [])[:rows]


def _parse_authors(item: dict) -> str:
    authors = []
    for a in item.get("authorships") or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append({"name": name, "affiliation": ""})
    return json.dumps(authors, ensure_ascii=False)


def _uninvert_abstract(inverted: dict | None) -> str:
    """还原 OpenAlex abstract_inverted_index 到纯文本"""
    if not inverted:
        return ""
    positions = []
    for word, idxs in inverted.items():
        for idx in idxs:
            positions.append((idx, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _pub_date(item: dict) -> datetime:
    pd = item.get("publication_date") or ""
    try:
        return datetime.strptime(pd[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        logger.warning("OpenAlex publication_date 异常: %s (%s)", pd, item.get("doi"))
        return datetime.now(UTC)


def _source_name(item: dict) -> str:
    src = item.get("primary_location") or {}
    source = src.get("source") or {}
    return source.get("display_name") or source.get("host_organization_name") or "Crossref"


def _pdf_url(item: dict, doi: str) -> str:
    oa = item.get("best_oa_location") or {}
    pdf = oa.get("pdf_url") or oa.get("landing_page_url")
    if pdf and pdf.startswith("http"):
        return re.sub(r"^http://", "https://", pdf)
    return f"https://doi.org/{doi}"


def save_openalex_item(db, item: dict, pub: dict, profile_id: int | None = None):
    """OpenAlex 记录入库（source=doi），按 DOI 去重；已存在则补挂档案关联"""
    from arxiv_pulse.models import Paper

    doi_raw = (item.get("doi") or "").strip().lower().replace("https://doi.org/", "")
    if not doi_raw:
        return None
    doi = doi_raw

    pub_name = pub.get("name") or _source_name(item)

    with db.get_session() as session:
        paper = session.query(Paper).filter_by(doi=doi).first()
        if paper is not None:
            if profile_id is not None:
                from arxiv_pulse.services.profile_service import attach_profile

                attach_profile(db, paper, profile_id)
            return paper

        title = item.get("title") or ""
        paper = Paper(
            arxiv_id=doi,
            doi=doi,
            title=title,
            authors=_parse_authors(item),
            abstract=_uninvert_abstract(item.get("abstract_inverted_index")),
            categories=pub_name,
            primary_category=pub_name,
            published=_pub_date(item),
            pdf_url=_pdf_url(item, doi),
            journal_ref=pub_name,
            comment=item.get("type") or "",
            search_query=f"publisher:{pub.get('key', 'openalex')}",
            relevance_score=0.0,
            source="doi",
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)

    if profile_id is not None:
        from arxiv_pulse.services.profile_service import attach_profile

        attach_profile(db, paper, profile_id)
    return paper
