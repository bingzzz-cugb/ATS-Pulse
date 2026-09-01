"""
Crossref 期刊目录服务

从 Crossref /journals 分页拉取全量期刊（约 6-7 万本）存入本地库，
支持模糊搜索：标题包含 / ISSN 包含 / 显著词首字母缩写包含（RSE → Remote Sensing of Environment）
"""

import csv
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from sqlalchemy import case, func, or_

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}

# SJR 二区以上（Q1+Q2）期刊清单，由 Scimago Journal Rank 数据生成，随仓库分发
_SJR_CSV = Path(__file__).resolve().parent.parent / "data" / "sjr_journals_q12.csv"

# 缩写匹配时忽略的冠词/介词/连词，"Remote Sensing of Environment" 仅取显著词首字母 → RSE
_STOPWORDS = {"of", "and", "the", "for", "in", "on", "a", "an", "to", "with",
              "at", "by", "from", "or", "is", "as"}

_STATE = {"syncing": False, "pages": 0, "count": 0, "total": None, "error": None}
_LOCK = threading.Lock()

# 常见期刊种子：/journals 的 offset 上限 10 万（约 35% 条目翻不到，含部分主流期刊），
# 保证这些期刊及其缩写（RSE/TGRS/ISPRS…）本地必中
SEED_JOURNALS = [
    ("1558-0644", "IEEE Transactions on Geoscience and Remote Sensing", "IEEE"),
    ("0034-4257", "Remote Sensing of Environment", "Elsevier"),
    ("1545-598X", "IEEE Geoscience and Remote Sensing Letters", "IEEE"),
    ("0924-2716", "ISPRS Journal of Photogrammetry and Remote Sensing", "Elsevier"),
    ("1939-1404", "IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing", "IEEE"),
    ("0022-4073", "Journal of Quantitative Spectroscopy and Radiative Transfer", "Elsevier"),
    ("1867-1381", "Atmospheric Measurement Techniques", "Copernicus Publications"),
    ("1680-7316", "Atmospheric Chemistry and Physics", "Copernicus Publications"),
    ("1094-4087", "Optics Express", "Optica Publishing Group"),
    ("0028-0836", "Nature", "Springer Nature"),
    ("2041-1723", "Nature Communications", "Springer Nature"),
    ("2045-2322", "Scientific Reports", "Springer Nature"),
    ("0036-8075", "Science", "American Association for the Advancement of Science"),
    ("0094-8276", "Geophysical Research Letters", "Wiley"),
    ("2169-8996", "Journal of Geophysical Research: Atmospheres", "Wiley"),
    ("0003-6935", "Applied Optics", "Optica Publishing Group"),
]


def make_acronym(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title or "")
    letters = [w[0] for w in words if w.lower() not in _STOPWORDS]
    return "".join(letters).upper()


def get_state() -> dict:
    with _LOCK:
        return dict(_STATE)


def _get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.warning("期刊目录请求失败 %s: %s", url[:60], e)
        return None


def _parse_crossref_rows(items: list) -> list[dict]:
    """Crossref /journals 的 ISSN 字段是大写 `ISSN`（列表），且 title 是字符串"""
    rows = []
    for it in items:
        issns = it.get("ISSN") or it.get("issn") or []
        if not issns:
            continue
        title = str(it.get("title") or "")
        if not title:
            continue
        rows.append({
            "issn": issns[0],
            "title": title,
            "publisher": (it.get("publisher") or "")[:200],
            "acronym": make_acronym(title),
        })
    return rows


def _insert_seed(session) -> None:
    from sqlalchemy import insert

    from arxiv_pulse.models import CrossrefJournal

    rows = [
        {"issn": issn, "title": title, "publisher": publisher,
         "acronym": make_acronym(title), "quartile": "Q1"}
        for issn, title, publisher in SEED_JOURNALS
    ]
    stmt = insert(CrossrefJournal).prefix_with("OR IGNORE")
    session.execute(stmt, rows)
    session.commit()


def sync_journals_catalog(db) -> dict:
    """从 SJR 二区以上清单导入期刊目录（按 ISSN 去重，可重复调用）；返回统计"""
    from sqlalchemy import insert

    from arxiv_pulse.models import CrossrefJournal

    with _LOCK:
        if _STATE["syncing"]:
            return {"ok": False, "reason": "already_syncing"}
        _STATE.update({"syncing": True, "pages": 0, "count": 0, "total": None, "error": None})

    if not _SJR_CSV.exists():
        msg = f"缺少分区数据文件: {_SJR_CSV}"
        logger.error(msg)
        with _LOCK:
            _STATE.update({"syncing": False, "error": msg})
        return {"ok": False, "error": msg}

    try:
        with db.get_session() as session:
            session.query(CrossrefJournal).delete()
            session.commit()
            _insert_seed(session)
            batch = []
            with open(_SJR_CSV, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    issn = (row.get("issn") or "").strip()
                    title = (row.get("title") or "").strip()
                    if not issn or not title:
                        continue
                    sjr_raw = (row.get("sjr") or "").strip()
                    batch.append({
                        "issn": issn,
                        "title": title,
                        "publisher": (row.get("publisher") or "")[:200],
                        "acronym": make_acronym(title),
                        "quartile": (row.get("quartile") or "").strip() or None,
                        "sjr": float(sjr_raw) if sjr_raw else None,
                    })
            for i in range(0, len(batch), 2000):
                stmt = insert(CrossrefJournal).prefix_with("OR IGNORE")
                session.execute(stmt, batch[i:i + 2000])
                session.commit()
            with _LOCK:
                _STATE["pages"] = 1
                _STATE["total"] = len(batch)
                _STATE["count"] = session.query(func.count(CrossrefJournal.id)).scalar() or 0
        logger.info("期刊目录导入完成: %d 行, 库内 %d 本", len(batch), _STATE["count"])
        return {"ok": True, "pages": 1, "count": _STATE["count"]}
    except Exception as e:
        logger.exception("期刊目录导入异常")
        with _LOCK:
            _STATE["error"] = str(e)[:200]
        return {"ok": False, "error": str(e)[:200]}
    finally:
        with _LOCK:
            _STATE["syncing"] = False


def search_journals(db, query: str, limit: int = 50) -> list[dict]:
    """本地模糊搜索 + 远程兜底：本地命中不足时查 Crossref query 全库，命中即回填本地"""
    from sqlalchemy import insert

    from arxiv_pulse.models import CrossrefJournal

    q = (query or "").strip()
    with db.get_session() as session:
        stmt = session.query(CrossrefJournal)
        if q:
            like = f"%{q}%"
            prefix_like = f"{q}%"
            stmt = stmt.filter(or_(
                CrossrefJournal.title.ilike(like),
                CrossrefJournal.issn.ilike(like),
                CrossrefJournal.acronym.ilike(like),
            )).order_by(
                case(
                    (CrossrefJournal.title.ilike(prefix_like), 0),
                    (CrossrefJournal.acronym.ilike(prefix_like), 1),
                    else_=2,
                ),
                CrossrefJournal.title,
            )
        else:
            stmt = stmt.order_by(CrossrefJournal.title)
        rows = stmt.limit(limit).all()
        local = [
            {"issn": r.issn, "title": r.title, "publisher": r.publisher, "acronym": r.acronym,
             "quartile": r.quartile, "sjr": r.sjr}
            for r in rows
        ]

    if not q or len(local) >= limit:
        return local

    remote = _search_remote(q, limit - len(local))
    if not remote:
        return local

    # 远程命中回填本地库，下次搜索秒出
    try:
        with db.get_session() as session:
            stmt = insert(CrossrefJournal).prefix_with("OR IGNORE")
            session.execute(stmt, remote)
            session.commit()
    except Exception:
        logger.exception("期刊目录远程结果回填失败")

    local_issns = {j["issn"] for j in local}
    merged = list(local) + [j for j in remote if j["issn"] not in local_issns]
    return merged[:limit]


def _search_remote(q: str, limit: int) -> list[dict]:
    """实时查 Crossref /journals?query= 全库搜索"""
    url = "https://api.crossref.org/journals?" + urllib.parse.urlencode(
        {"query": q, "rows": str(min(limit, 8)), "mailto": "arxiv-pulse@example.com"}
    )
    data = _get_json(url)
    if not data:
        return []
    return _parse_crossref_rows(data.get("message", {}).get("items", []) or [])


def ensure_catalog_synced(db) -> dict:
    """返回当前状态；库空且未在同步时后台启动一次全量同步"""
    from arxiv_pulse.models import CrossrefJournal

    with db.get_session() as session:
        count = session.query(func.count(CrossrefJournal.id)).scalar() or 0

    state = get_state()
    if count == 0 and not state["syncing"]:
        threading.Thread(
            target=sync_journals_catalog, args=(db,), daemon=True, name="journal-catalog-sync"
        ).start()
        state = get_state()
    return {"syncing": state["syncing"], "count": count, "pages": state["pages"],
            "total": state["total"], "error": state["error"]}


def force_sync(db) -> dict:
    """手动触发一次全量同步（后台线程，已在同步时直接返回）"""
    state = get_state()
    if state["syncing"]:
        return {"ok": False, "reason": "already_syncing", **state}
    threading.Thread(
        target=sync_journals_catalog, args=(db,), daemon=True, name="journal-catalog-sync"
    ).start()
    time.sleep(0.05)
    return {"ok": True, **get_state()}
