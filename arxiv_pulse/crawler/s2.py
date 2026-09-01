"""
Semantic Scholar 检索器 - 跨会议/期刊/预印本混合源
"""

import json
import time
import urllib.parse
from datetime import UTC, datetime

from arxiv_pulse.crawler.publisher import _http_get_json

_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_DOI_URL_TMPL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{}"


def _s2_date_range(date_from: str | None, date_to: str | None) -> str:
    if date_from and date_to:
        return f"{date_from},{date_to}"
    if date_from:
        return f"{date_from},{date_from}"
    return ""


def search_s2_items(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    rows: int = 25,
    api_key: str | None = None,
    log_cb=None,
) -> list[dict]:
    params = {
        "query": query,
        "limit": str(min(rows, 100)),
        "fields": "title,abstract,venue,year,publicationDate,externalIds,openAccessPdf,authors,url",
    }
    if date_from or date_to:
        params["publicationDateOrYear"] = _s2_date_range(date_from, date_to)
    url = f"{_S2_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}
    if api_key:
        headers["x-api-key"] = api_key
    # S2 限流是 5 分钟窗口级的，短重试大概率仍失败；失败要快速放行让更新流程收尾
    for attempt in range(2):
        data = _http_get_json(url, headers, timeout=25)
        if data is not None:
            return data.get("data", [])
        if attempt == 0 and log_cb:
            log_cb("S2 搜索请求失败（可能限流），重试一次...")
        time.sleep(3 * (attempt + 1))
    if log_cb:
        log_cb("S2 搜索仍失败（限流），跳过本次 S2 检索")
    return []


def fetch_s2_item_by_doi(doi: str, api_key: str | None = None) -> dict | None:
    """按 DOI 直接获取 S2 论文记录（与 search 返回同一结构）；失败/限流/不存在返回 None"""
    fields = "title,abstract,venue,year,publicationDate,externalIds,openAccessPdf,authors,url"
    url = (
        f"{_S2_DOI_URL_TMPL}{urllib.parse.quote(doi.lower().strip(), safe='')}"
        f"?{urllib.parse.urlencode({'fields': fields})}"
    )
    headers = {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}
    if api_key:
        headers["x-api-key"] = api_key
    return _http_get_json(url, headers, timeout=20)


def _parse_authors(item: dict) -> str:
    authors = []
    for a in item.get("authors") or []:
        if a.get("name"):
            authors.append({"name": a["name"], "affiliation": ""})
    return json.dumps(authors, ensure_ascii=False)


def save_s2_item(db, item: dict, profile_id: int | None = None):
    """S2 命中入库：优先 arXiv id，其次 DOI；两者皆无则跳过；已存在则补挂档案关联"""
    from arxiv_pulse.models import Paper

    external = item.get("externalIds") or {}
    arxiv_id = external.get("ArXiv")
    doi = (external.get("DOI") or "").lower()
    if not arxiv_id and not doi:
        return None

    entry_id = arxiv_id or doi

    with db.get_session() as session:
        paper = session.query(Paper).filter_by(arxiv_id=entry_id).first()
        if paper is None:
            title = item.get("title") or ""
            year = item.get("year") or datetime.now().year
            date = item.get("publicationDate") or f"{year}-01-01"
            try:
                published = datetime.strptime(date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                published = datetime(year, 1, 1, tzinfo=UTC)

            pdf_url = (item.get("openAccessPdf") or {}).get("url")
            if not pdf_url and doi:
                pdf_url = f"https://doi.org/{doi}"
            if not pdf_url and arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            paper = Paper(
                arxiv_id=entry_id,
                doi=doi or None,
                title=title,
                authors=_parse_authors(item),
                abstract=item.get("abstract") or "",
                categories=item.get("venue") or "",
                primary_category=item.get("venue") or "",
                published=published,
                pdf_url=pdf_url,
                journal_ref=item.get("venue") or None,
                comment="",
                search_query=f"s2:{item.get('paperId', '')}",
                relevance_score=0.0,
                source="arxiv" if arxiv_id else "doi",
            )
            session.add(paper)
            session.commit()
            session.refresh(paper)

    if profile_id is not None:
        from arxiv_pulse.services.profile_service import attach_profile

        attach_profile(db, paper, profile_id)
    return paper
