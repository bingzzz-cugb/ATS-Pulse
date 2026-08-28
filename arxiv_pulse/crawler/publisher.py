"""
期刊论文爬虫：通过 Crossref 元数据 + Semantic Scholar 摘要，追踪非 arXiv 来源的期刊论文。
"""

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from arxiv_pulse.core import Config, Database
from arxiv_pulse.models import Paper

logger = logging.getLogger(__name__)

# 期刊白名单 = 质量过滤规则（能进这个列表的本身就是顶刊）
PUBLISHERS = [
    {
        "key": "tgrs",
        "name": "IEEE Transactions on Geoscience and Remote Sensing",
        "issn": "1558-0644",
        "categories": "IEEE TGRS",
    },
    {
        "key": "science",
        "name": "Science",
        "issn": "0036-8075",
        "categories": "Science",
    },
]

CROSSREF_HEADERS = {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}
S2_HEADERS = {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}


def _http_get_json(url: str, headers: dict, timeout: int = 30) -> dict | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.warning("请求失败 %s: %s", url[:80], e)
        return None


def fetch_crossref_items(issn: str, days_back: int = 7, rows: int = 200) -> list[dict]:
    """按 Crossref deposit 日期拉取期刊近 N 天新增记录（deposit 日期粒度最细）"""
    since = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    params = {
        "filter": f"from-deposit-date:{since}",
        "sort": "deposited",
        "order": "desc",
        "rows": str(rows),
        "mailto": "arxiv-pulse@example.com",
        "select": "DOI,title,author,abstract,container-title,published,published-online,published-print,deposited,link,URL",
    }
    url = f"https://api.crossref.org/journals/{urllib.parse.quote(issn)}/works?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, CROSSREF_HEADERS)
    if not data:
        return []
    return data.get("message", {}).get("items", [])


def fetch_s2_abstract(doi: str, retries: int = 4) -> tuple[str | None, str | None]:
    """从 Semantic Scholar 获取摘要与开放 PDF 链接，带退避重试（429 限流）"""
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}"
        "?fields=title,abstract,publicationDate,venue,openAccessPdf"
    )
    for attempt in range(retries):
        data = _http_get_json(url, S2_HEADERS, timeout=20)
        if data is None:
            time.sleep(3 * (attempt + 1))
            continue
        if isinstance(data, dict):
            abstract = data.get("abstract")
            if abstract and not abstract.startswith("Notice:") and len(abstract) > 50:
                return abstract, (data.get("openAccessPdf") or {}).get("url")
            return None, (data.get("openAccessPdf") or {}).get("url")
        time.sleep(3 * (attempt + 1))
    return None, None


def _pub_date(item: dict) -> datetime | None:
    """出版日期推断：online > print > published > deposit（deposit 对 IEEE 等近似为在线发布日）"""
    for key in ("published-online", "published-print", "published", "issued", "deposited"):
        parts = item.get(key, {}).get("date-parts", [None])
        if parts and parts[0] and len(parts[0]) >= 3:
            try:
                return datetime(*parts[0][:3], tzinfo=UTC)
            except ValueError:
                continue
        if parts and parts[0] and len(parts[0]) >= 2:
            try:
                return datetime(parts[0][0], parts[0][1], 1, tzinfo=UTC)
            except ValueError:
                continue
    return datetime.now(UTC)


def _clean_title(title: list[str] | str | None) -> str:
    text = title[0] if isinstance(title, list) and title else (title or "")
    text = re.sub(r"<[^>]+>", "", text).strip()
    return text


def save_doi_paper(item: dict, pub: dict, s2_result: tuple[str | None, str | None] | None = None,
                   db: Database | None = None) -> Paper | None:
    """将一条 Crossref 记录转换为 Paper（source=doi）并去重保存"""
    db = db or Database()
    doi = (item.get("DOI") or "").lower()
    if not doi:
        return None
    if db.paper_exists(doi):
        return None

    s2_abstract, s2_pdf = s2_result if s2_result else (None, None)
    abstract = (item.get("abstract") or "").strip() or s2_abstract or ""
    if abstract.startswith("<jats:") or "<" in abstract[:30]:
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    crossref_links = item.get("link") or []
    pdf_url = s2_pdf
    if not pdf_url:
        pdf_url = crossref_links[0].get("URL") if crossref_links else None
    if not pdf_url:
        pdf_url = f"https://doi.org/{doi}"
    else:
        pdf_url = pdf_url.replace("http://", "https://")

    authors = []
    for a in item.get("author") or []:
        name = " ".join(filter(None, [a.get("given"), a.get("family")]))
        if name:
            authors.append({"name": name, "affiliation": ""})

    paper = Paper(
        arxiv_id=doi,
        doi=doi,
        title=_clean_title(item.get("title")),
        authors=json.dumps(authors, ensure_ascii=False),
        abstract=abstract,
        categories=pub.get("categories", pub["name"]),
        primary_category=pub["name"],
        published=_pub_date(item),
        updated=None,
        pdf_url=pdf_url,
        journal_ref=pub["name"],
        comment="",
        search_query=f"publisher:{pub['key']}",
        relevance_score=0.0,
        source="doi",
    )
    try:
        db.add_paper(paper)
        return paper
    except Exception as e:
        logger.error("保存 DOI 论文失败: %s (%s)", doi, e)
        return None


def sync_publisher(pub: dict, days_back: int = 7, limit: int = 200,
                   cancel_check: Callable[[], bool] | None = None) -> dict:
    """同步单个期刊最近的论文，cancel_check 返回 True 时提前退出"""
    db = Database()
    items = fetch_crossref_items(pub["issn"], days_back=days_back, rows=limit)
    new_papers = 0
    failed = 0
    for item in items:
        if cancel_check and cancel_check():
            return {"publisher": pub["key"], "fetched": len(items), "new": new_papers,
                    "failed": failed, "cancelled": True}
        doi = (item.get("DOI") or "").lower()
        if not doi:
            continue
        if db.paper_exists(doi):
            continue
        s2_result = None
        if not (item.get("abstract") or "").strip():
            s2_result = fetch_s2_abstract(doi)
        if save_doi_paper(item, pub, s2_result, db) is not None:
            new_papers += 1
        else:
            failed += 1
        time.sleep(0.5)
    return {"publisher": pub["key"], "fetched": len(items), "new": new_papers, "failed": failed}


def sync_all_publishers(days_back: int = 7, pub_keys: list[str] | None = None,
                        cancel_check: Callable[[], bool] | None = None) -> dict:
    """同步期刊，pub_keys 为空时同步所有配置期刊；cancel_check 为 True 时提前退出"""
    total_new = 0
    results = []
    for pub in PUBLISHERS:
        if cancel_check and cancel_check():
            break
        if pub_keys is not None and pub["key"] not in pub_keys:
            continue
        try:
            r = sync_publisher(pub, days_back=days_back, cancel_check=cancel_check)
        except Exception as e:
            r = {"publisher": pub["key"], "error": str(e)}
        results.append(r)
        total_new += r.get("new", 0)
    return {"new": total_new, "publishers": results}
