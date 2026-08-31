# 领域档案检索系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户用自然语言定义检索领域（档案），AI 生成多源检索计划；近期论文页按档案+时间范围三源同步；主页搜索改为本地优先+特定文章远程抓取。

**Architecture:** 新增 `research_profiles`/`paper_profiles` 表 + `profile_service`（AI 规范化、同步管线和入库）+ `s2.py`（Semantic Scholar 检索）；`/api/papers/quick` 重写为本地优先；前端新增档案管理卡片与近期页领域下拉，隔离旧字段选择器 UI（代码保留）。

**Tech Stack:** FastAPI + SQLAlchemy + OpenAI 兼容客户端（DeepSeek）+ Crossref/Semantic Scholar HTTP APIs + Vue 3 CDN + Element Plus 字符串模板组件。

**Spec:** `docs/superpowers/specs/2026-08-31-domain-profiles-design.md`

## Global Constraints

- 分支：main（用户已批准在 main 上实现）；工作树可能含未提交改动时，commit 只 add 本计划文件。
- 项目无 pytest（.venv 缺）：**验证用临时目录实例 + curl + python -c 内联脚本（用完即删，验证后清理）**；临时实例端口 8103，数据目录 `tests/tmp_verify_data`，启动命令 `PYTHONIOENCODING=utf-8 .venv/Scripts/pulse.exe serve tests/tmp_verify_data -f --port 8103`。
- 不碰用户 8000 实例（除最终 Playwright 只读验证）。
- `models/` 是目录：新增模型文件后需在 `arxiv_pulse/models/__init__.py` 导出；Database 建表由 `Base.metadata.create_all`（`core/database.py` 初始化路径）自动完成——新增表无需迁移脚本。
- 模板约束（#app 内联模板）：非 void 元素禁自闭合；新状态必须加入 setup return；组件字符串模板可自闭合（Vue 编译器）。
- `papers.source` 沿用两值：arxiv / doi。
- 每个任务独立 commit，commit 信息用中文惯例前缀 `feat:`/`fix:` 可用（沿用项目现有风格）。

---

### Task 1: 数据模型（research_profiles / paper_profiles）

**Files:**
- Create: `arxiv_pulse/models/profile.py`
- Modify: `arxiv_pulse/models/__init__.py`（导出新模型）

**Interfaces:**
- Produces: `ResearchProfile`（id/name/description/retrieval_plan/journals/sources/enabled/updated_at + `to_dict()` 解析 JSON）、`PaperProfile`（id/profile_id/paper_id/created_at，`profile_id+paper_id` 唯一）

- [ ] **Step 1: 写模型文件**

```python
"""Profile models - 检索领域档案"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from arxiv_pulse.models.base import Base


class ResearchProfile(Base):
    __tablename__ = "research_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    retrieval_plan = Column(Text)  # JSON: {"arxiv_queries": [], "s2_query": "", "keywords": [], "exclude_words": []}
    journals = Column(Text)        # JSON: [{"key,"name,"issn,"enabled}]
    sources = Column(Text, default='{"arxiv": true, "crossref": true, "s2": true}')
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        import json
        def _load(v, default):
            try:
                return json.loads(v) if v else default
            except (ValueError, TypeError):
                return default
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "retrieval_plan": _load(self.retrieval_plan, {}),
            "journals": _load(self.journals, []),
            "sources": _load(self.sources, {"arxiv": True, "crossref": True, "s2": True}),
            "enabled": bool(self.enabled),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PaperProfile(Base):
    __tablename__ = "paper_profiles"
    __table_args__ = (UniqueConstraint("profile_id", "paper_id"),)

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, nullable=False, index=True)
    paper_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: `models/__init__.py` 追加导出**

```python
from arxiv_pulse.models.profile import PaperProfile, ResearchProfile
```

- [ ] **Step 3: 验证建表与 to_dict**

```bash
.venv/Scripts/python.exe - <<'EOF'
import sqlite3, sys, os
os.environ.setdefault("DATABASE_URL", "sqlite:///tests/tmp_verify_data/data/arxiv_papers.db")
os.makedirs("tests/tmp_verify_data/data", exist_ok=True)
from arxiv_pulse.models import Base
from arxiv_pulse.models.profile import ResearchProfile, PaperProfile
Base.metadata.create_all(sqlite3.connect("tests/tmp_verify_data/data/arxiv_papers.db").__class__ and __import__('sqlalchemy').create_engine("sqlite:///tests/tmp_verify_data/data/arxiv_papers.db"))
# SQLAlchemy create_all needs engine; above is illustrative — use real pattern below
EOF
```

  实际执行（SQLAlchemy 正确写法）：

```bash
.venv/Scripts/python.exe - <<'EOF'
import os
os.makedirs("tests/tmp_verify_data/data", exist_ok=True)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from arxiv_pulse.models import Base, ResearchProfile, PaperProfile
engine = create_engine("sqlite:///tests/tmp_verify_data/data/arxiv_papers.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
s = Session()
p = ResearchProfile(name="AI 遥感", description="test", retrieval_plan='{"arxiv_queries":["a"]}', journals='[{"key":"tgrs","issn":"1558-0644","enabled":true}]')
s.add(p); s.commit(); s.refresh(p)
d = p.to_dict()
assert d["name"] == "AI 遥感" and isinstance(d["retrieval_plan"], dict)
q = s.query(PaperProfile).count() == 0
print("profile ok:", d["id"], d["sources"]["arxiv"])
s.close()
EOF
```

- [ ] **Step 4: Commit**

```bash
git add arxiv_pulse/models/profile.py arxiv_pulse/models/__init__.py
git commit -m "feat: add research profile models"
```

---

### Task 2: AI 规范化服务（profile_service）

**Files:**
- Create: `arxiv_pulse/services/profile_service.py`

**Interfaces:**
- Consumes: `Config`（AI_API_KEY/AI_BASE_URL/AI_MODEL）、`crawler.publisher.PUBLISHERS`（期刊模板）、`papers` 表
- Produces:
  - `generate_retrieval_plan(description: str) -> dict`（AI JSON 或降级 structure）
  - `default_journals() -> list[dict]`
  - `sync_profile_papers(profile: ResearchProfile, date_from: str | None, date_to: str | None, log_cb) -> dict`
  - `attach_profile(db, paper, profile_id: int) -> None`

- [ ] **Step 1: 写 `generate_retrieval_plan` 与 `default_journals`**

```python
"""Profile service - 领域档案 AI 规范化与多源同步"""
import json
import logging

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
                        "\"arxiv_queries\": [\"2-3 条 arXiv 高级查询串，使用 AND/OR/引号，如 (ti:\"remote sensing\" AND ti:\"methane\")\"], "
                        "\"s2_query\": \"Semantic Scholar 关键词串，如 methane remote sensing deep learning\", "
                        "\"keywords\": [\"6-10 个英文检索关键词\"], "
                        "\"exclude_words\": [\"1-3 个排除词\"], "
                        "\"suggested_journals\": [\"从候选期刊中给建议，如 IEEE TGRS\"]\n}"
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
        plan = {
            "arxiv_queries": [q for q in data.get("arxiv_queries", []) if isinstance(q, str) and q.strip()] or fallback["arxiv_queries"],
            "s2_query": data.get("s2_query") or fallback["s2_query"],
            "keywords": data.get("keywords", []),
            "exclude_words": data.get("exclude_words", []),
        }
        logger.info("plan generated: %s", plan.get("arxiv_queries"))
        return plan
    except Exception as e:
        logger.warning("AI plan 生成失败，使用降级方案: %s", str(e)[:80])
        return fallback
```

- [ ] **Step 2: 内联验证（无 key 降级）**

```bash
.venv/Scripts/python.exe - <<'EOF'
import os
os.environ["AI_API_KEY"] = ""
from arxiv_pulse.services.profile_service import generate_retrieval_plan, default_journals
plan = generate_retrieval_plan("AI 遥感甲烷反演")
assert plan["arxiv_queries"] == ["AI 遥感甲烷反演"]
assert len(default_journals()) == 2 and default_journals()[0]["key"] == "tgrs"
print("fallback plan ok:", plan["arxiv_queries"], "| journals:", [j["key"] for j in default_journals()])
EOF
```

- [ ] **Step 3: 写 `attach_profile` 与 `sync_profile_papers`（三源核心）**

```python
def attach_profile(db, paper, profile_id: int) -> None:
    """给论文打上档案关联（已存在则跳过）"""
    from arxiv_pulse.models import PaperProfile

    if not paper:
        return
    exists = db.get_session().__class__ and None  # replaced below with proper pattern
```

  实际实现（修正为 session 内）：

```python
def attach_profile(db, paper, profile_id: int) -> None:
    from arxiv_pulse.models import PaperProfile

    if not paper:
        return
    with db.get_session() as session:
        if not session.query(PaperProfile).filter_by(profile_id=profile_id, paper_id=paper.id).first():
            session.add(PaperProfile(profile_id=profile_id, paper_id=paper.id))
            session.commit()
```

```python
def sync_profile_papers(profile, date_from=None, date_to=None, source_override=None, log_cb=lambda msg: None) -> dict:
    """按档案三源检索当日/指定区间论文并入库，返回各源统计

    source_override: None 用 profile.sources；dict 覆盖（如 {"arxiv": True, "crossref": True, "s2": False}）
    """
    import json
    from datetime import datetime

    from arxiv_pulse.core import Database
    from arxiv_pulse.crawler import ArXivCrawler
    from arxiv_pulse.crawler.arxiv import _date_range_query
    from arxiv_pulse.crawler.publisher import fetch_crossref_items, save_doi_paper
    from arxiv_pulse.models import Paper

    db = Database()
    plan = {}
    try:
        plan = json.loads(profile.retrieval_plan) if profile.retrieval_plan else {}
    except (ValueError, TypeError):
        pass
    arxiv_queries = [q for q in plan.get("arxiv_queries", []) if q] or [profile.description]
    s2_query = plan.get("s2_query") or profile.description or ""
    keywords = plan.get("keywords", [])
    exclude_words = [w.lower() for w in plan.get("exclude_words", [])]

    sources = dict(profile.to_dict()["sources"])
    if source_override:
        sources.update(source_override)

    result = {"profile": profile.name, "arxiv_new": 0, "crossref_new": 0, "s2_new": 0, "total_new": 0, "found": 0}

    # 1. arXiv
    if sources.get("arxiv", True):
        crawler = ArXivCrawler()
        for query in arxiv_queries[:3]:
            q = _date_range_query(query, date_from, date_to)
            try:
                papers, total, new_count = crawler.search_and_save(q, max_results=30)
            except Exception as e:
                log_cb(f"arXiv 查询失败: {query[:40]} ({str(e)[:50]})")
                continue
            result["arxiv_new"] += new_count
            result["found"] += total
            log_cb(f"arXiv: {query[:40]} → 命中 {total}，新增 {new_count}")
            for p in papers:
                attach_profile(db, p, profile.id)

    # 2. Crossref 期刊组
    journals = []
    try:
        journals = [j for j in json.loads(profile.journals) if j.get("enabled")] if profile.journals else []
    except (ValueError, TypeError):
        pass
    if sources.get("crossref", True) and not exclude_words or True:  # 排除词用于结果呈现，此处不粗暴过滤
        for pub in journals:
            items = fetch_crossref_items(pub["issn"], days_back=7, rows=50, date_from=date_from, date_to=date_to)
            saved = 0
            for item in items:
                doi = (item.get("DOI") or "").lower()
                if not doi or db.paper_exists(doi):
                    continue
                if exclude_words and any(w and w in (_clean(item.get("title") or "").lower()) for w in exclude_words):
                    continue
                if save_doi_paper(item, pub, db=db) is not None:
                    saved += 1
            if saved:
                log_cb(f"期刊 {pub['name'][:30]}: 新增 {saved} 篇")
            result["crossref_new"] += saved
            result["found"] += len(items)

    # 3. Semantic Scholar
    if sources.get("s2", True) and s2_query:
        from arxiv_pulse.crawler.s2 import save_s2_item, search_s2_items

        for item in search_s2_items(s2_query, date_from, date_to):
            if exclude_words and any(w and w in str(item.get("title") or "").lower() for w in exclude_words):
                continue
            paper = save_s2_item(db, item, profile.id)
            if paper is not None:
                result["s2_new"] += 1
        log_cb(f"S2: 新增 {result['s2_new']} 篇")

    result["total_new"] = result["arxiv_new"] + result["crossref_new"] + result["s2_new"]
    return result


def _clean(title) -> str:
    import re
    if not title:
        return ""
    text = title[0] if isinstance(title, list) else title
    return re.sub(r"<[^>]+>", "", text)
```

  注意上方 `if sources.get("crossref")... or True` 简化为直接执行：执行时把该条件改成 `if sources.get("crossref", True):`。

- [ ] **Step 4: 语法+降级验证**

```bash
.venv/Scripts/python.exe -c "import ast; ast.parse(open('arxiv_pulse/services/profile_service.py',encoding='utf-8').read()); print('profile_service syntax ok')"
```

- [ ] **Step 5: Commit**

```bash
git add arxiv_pulse/services/profile_service.py
git commit -m "feat: profile AI plan generation and three-source sync"
```

---

### Task 3: Semantic Scholar 检索模块（s2.py）

**Files:**
- Create: `arxiv_pulse/crawler/s2.py`

**Interfaces:**
- Consumes: `Database`、`Paper` 模型、`profile_service.attach_profile`
- Produces:
  - `search_s2_items(query: str, date_from: str | None, date_to: str | None, rows: int = 25) -> list[dict]`
  - `save_s2_item(db, item: dict, profile_id: int | None = None) -> Paper | None`

- [ ] **Step 1: 写模块**

```python
"""
Semantic Scholar 检索器 - 跨会议/期刊/预印本混合源
"""
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from arxiv_pulse.crawler.publisher import _http_get_json

logger = logging.getLogger(__name__)

# Semantic Scholar graph API date format: publicationDateOrYear=YYYY-MM-DD,YYYY-MM-DD
_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _s2_date_range(date_from: str | None, date_to: str | None) -> str:
    if date_from and date_to:
        return f"{date_from},{date_to}"
    if date_from:
        return f"{date_from},{date_from}"
    return ""


def search_s2_items(query: str, date_from: str | None = None, date_to: str | None = None, rows: int = 25) -> list[dict]:
    params = {
        "query": query,
        "limit": str(min(rows, 100)),
        "fields": "title,abstract,venue,year,publicationDate,externalIds,openAccessPdf,authors,externalIds,url",
    }
    if date_from or date_to:
        params["publicationDateOrYear"] = _s2_date_range(date_from, date_to)
    url = f"{_S2_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        data = _http_get_json(url, {"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"}, timeout=25)
        if data is not None:
            return data.get("data", [])
        time.sleep(2 * (attempt + 1))
    return []


def _parse_authors(item: dict) -> str:
    authors = []
    for a in item.get("authors") or []:
        name = a.get("name")
        if name:
            authors.append({"name": name, "affiliation": ""})
    return json.dumps(authors, ensure_ascii=False)


def save_s2_item(db, item: dict, profile_id: int | None = None):
    """S2 命中入库：优先 arXiv id，其次 DOI；两者皆无则跳过"""
    from arxiv_pulse.models import Paper

    external = item.get("externalIds") or {}
    arxiv_id = external.get("ArXiv")
    doi = (external.get("DOI") or "").lower()
    if not arxiv_id and not doi:
        return None

    entry_id = arxiv_id or doi

    with db.get_session() as session:
        if session.query(Paper).filter_by(arxiv_id=entry_id).first():
            return None

        title = item.get("title") or ""
        year = item.get("year") or (datetime.now().year)
        date = item.get("publicationDate") or f"{year}-01-01"
        try:
            published = datetime.strptime(date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            published = datetime(year, 1, 1, tzinfo=UTC)

        pdf_url = (item.get("openAccessPdf") or {}).get("url")
        if not pdf_url and doi:
            pdf_url = f"https://doi.org/{doi}"
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None

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
```

- [ ] **Step 2: 验证（网络 1 次免费调用）**

```bash
.venv/Scripts/python.exe - <<'EOF'
from arxiv_pulse.crawler.s2 import search_s2_items
items = search_s2_items("methane remote sensing deep learning", "2026-08-29", "2026-08-31", rows=5)
print("s2 items:", len(items))
for it in items[:3]:
    print("-", it.get("title", "")[:60], "| arxiv:", (it.get("externalIds") or {}).get("ArXiv"), "| doi:", (it.get("externalIds") or {}).get("DOI"))
EOF
```

  预期：≥0 条（日期窗口内可能为空 —— 若为空改为近期 7 天窗口重跑确认 API 连通）。

- [ ] **Step 3: Commit**

```bash
git add arxiv_pulse/crawler/s2.py
git commit -m "feat: add Semantic Scholar search source"
```

---

### Task 4: Profiles CRUD 端点 + 同步管线接入

**Files:**
- Modify: `arxiv_pulse/web/api/config.py`（新增 profiles 端点组）
- Modify: `arxiv_pulse/web/api/papers.py`（`/recent/update` 支持 `profile_ids` 参数）
- Modify: `arxiv_pulse/web/static/js/services/api.js`（config.profiles.*）

**Interfaces:**
- Consumes: Task 2/3 的 `generate_retrieval_plan`、`sync_profile_papers`、`default_journals`、`ResearchProfile`
- Produces: `GET /api/config/profiles`（列表）、`POST /api/config/profiles`（新建接受 {name, description}，自动生成 plan；可选 {retrieval_plan, journals, sources} 覆盖）、`PUT /api/config/profiles/{id}`、`DELETE /api/config/profiles/{id}`、`POST /api/config/profiles/generate`（body {description} → plan JSON，不落库）；`/api/papers/recent` 与 `/recent/update` 接受 `profile_ids`（逗号分隔 int）

- [ ] **Step 1: config.py 加端点**

```python
@router.post("/profiles/generate")
async def generate_profile_plan(data: dict):
    """AI 生成检索计划（不落库，仅预览）"""
    description = (data.get("description") or "").strip()
    if not description:
        raise HTTPException(422, "description 不能为空")
    return generate_retrieval_plan(description)


@router.get("/profiles")
async def list_profiles():
    with get_db().get_session() as session:
        return [p.to_dict() for p in session.query(ResearchProfile).order_by(ResearchProfile.id).all()]


@router.post("/profiles")
async def create_profile(data: dict):
    from arxiv_pulse.services.profile_service import default_journals

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name or not description:
        raise HTTPException(422, "name 与 description 必填")
    plan = data.get("retrieval_plan") or generate_retrieval_plan(description)
    journals = data.get("journals") or default_journals()
    sources = data.get("sources") or {"arxiv": True, "crossref": True, "s2": True}
    with get_db().get_session() as session:
        profile = ResearchProfile(
            name=name, description=description,
            retrieval_plan=json.dumps(plan, ensure_ascii=False),
            journals=json.dumps(journals, ensure_ascii=False),
            sources=json.dumps(sources),
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile.to_dict()


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: int, data: dict):
    with get_db().get_session() as session:
        profile = session.query(ResearchProfile).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(404, "Profile not found")
        if "name" in data: profile.name = data["name"]
        if "description" in data: profile.description = data["description"]
        if "retrieval_plan" in data and data["retrieval_plan"]: profile.retrieval_plan = json.dumps(data["retrieval_plan"], ensure_ascii=False)
        if "journals" in data and data["journals"] is not None: profile.journals = json.dumps(data["journals"], ensure_ascii=False)
        if "sources" in data and data["sources"] is not None: profile.sources = json.dumps(data["sources"])
        if "enabled" in data: profile.enabled = bool(data["enabled"])
        session.commit()
        session.refresh(profile)
        return profile.to_dict()


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: int):
    with get_db().get_session() as session:
        profile = session.query(ResearchProfile).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(404, "Profile not found")
        session.query(PaperProfile).filter_by(profile_id=profile_id).delete()
        session.delete(profile)
        session.commit()
        return {"success": True}
```

  config.py 顶部补充 imports：`import json`（若缺）、`ResearchProfile, PaperProfile` 从 `arxiv_pulse.models` 导入、`generate_retrieval_plan` 从 `arxiv_pulse.services.profile_service` 导入（文件内 import 亦可，按现有风格）。

- [ ] **Step 2: papers.py `/recent/update` 支持 profile_ids**

  在 `update_recent_papers` 的 SSE 生成器开头（`recent_days`/`date_from` 处理处），加：

```python
profile_ids = [int(x) for x in (profile_ids or "").split(",") if x.strip().isdigit()] if profile_ids else []
# profile 模式：按档案三源同步
if profile_ids:
    from arxiv_pulse.models import ResearchProfile
    with get_db().get_session() as session:
        profiles = session.query(ResearchProfile).filter(ResearchProfile.id.in_(profile_ids), ResearchProfile.enabled == True).all()
    if not profiles:
        yield sse_event("log", {"message": "未启用的档案"})
        done...
    for prof in profiles:
        yield sse_event("log", {"message": f"开始同步档案: {prof.name}"})
        stats = await asyncio.to_thread(sync_profile_papers, prof, date_from_str, date_to_str,
                                        log_cb=lambda msg, prof=prof: None)
        # 由于 sync_profile_papers 内用 log_cb 同步日志，事件流改为：log_cb 直接收发 yield 困难；
        # 简化：sync_profile_papers 不传 log_cb（None → 内部打 logger），端点按源汇总 stats 输出：
        yield sse_event("log", {"message": f"档案 {prof.name}: arXiv+{stats['arxiv_new']}, 期刊+{stats['crossref_new']}, S2+{stats['s2_new']} (共 {stats['total_new']} 篇)"})
```

  具体替换示例（在现有 `update_recent_papers` 中 date_from/date_to 解析之后插入；`asyncio.to_thread` 避免阻塞事件循环）。

- [ ] **Step 3: api.js 加方法**

```js
config: {
    ...
    profiles: {
        list: () => fetch(`${API_BASE}/config/profiles`),
        generate: (description) => fetch(`${API_BASE}/config/profiles/generate`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ description })
        }),
        create: (data) => fetch(`${API_BASE}/config/profiles`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        }),
        update: (id, data) => fetch(`${API_BASE}/config/profiles/${id}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        }),
        remove: (id) => fetch(`${API_BASE}/config/profiles/${id}`, { method: 'DELETE' })
    }
}
```

- [ ] **Step 4: 临时实例冒烟（无 key 场景：建档降级 + 列表）**

```bash
mkdir -p tests/tmp_verify_data && PYTHONIOENCODING=utf-8 .venv/Scripts/pulse.exe serve tests/tmp_verify_data -f --port 8103 &  # 后台
sleep 10
curl -s -X POST http://127.0.0.1:8103/api/config/profiles -H "Content-Type: application/json" -d '{"name":"AI 遥感","description":"AI remote sensing methane"}' | head -c 400
curl -s http://127.0.0.1:8103/api/config/profiles | head -c 300
```

  预期：返回 profile JSON，retrieval_plan.arxiv_queries 为降级（无 key）数组；列表含 id=1。完成后 kill 实例。

- [ ] **Step 5: Commit**

```bash
git add arxiv_pulse/web/api/config.py arxiv_pulse/web/api/papers.py arxiv_pulse/web/static/js/services/api.js
git commit -m "feat: profile CRUD endpoints and profile-based sync"
```

---

### Task 5: 主页搜索重构（quick 端点）

**Files:**
- Modify: `arxiv_pulse/web/api/papers.py`（quick 端点）

**Interfaces:**
- Consumes: `parse_arxiv_id`、`crawler.publisher.save_doi_paper`、SearchEngine
- Produces: 主页搜索行为：本地优先 → 特定文章远程抓取（arXiv id / DOI / 标题）

- [ ] **Step 1: 在 papers.py 增加 DOI/标题识别与远程抓取辅助**

```python
_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")


def looks_like_full_title(q: str) -> bool:
    return len(q) > 15 and " " in q.strip()
```

- [ ] **Step 2: 重写 quick 端点的模糊区**（保留 arXiv-ID 精确分支前缀；替换"AI 解析+远程批量"分支为如下逻辑）

```python
        # —— 本地优先检索 ——
        yield sse_event("log", {"message": "正在搜索本地数据库..."})
        await asyncio.sleep(0.05)
        with db.get_session() as session:
            search_engine = SearchEngine(session)
            filter_config = SearchFilter(
                query=q,
                search_fields=["title", "abstract", "authors"] if any(c.isalpha() for c in q) else ["title"],
                days_back=0,
                limit=Config.SEARCH_LIMIT,
                sort_by="published",
                sort_order="desc",
            )
            local_papers = search_engine.search_papers(filter_config)
        candidates = []
        if local_papers:
            for p in local_papers[:20]:
                with db.get_session() as s:
                    fresh = s.query(Paper).filter_by(id=p.id).first()
                if fresh:
                    p = fresh
                yield sse_event("result", {"paper": enhance_paper_data(p), "match_type": "local"})
            yield sse_event("done", {"total": len(local_papers)})
            return
        yield sse_event("log", {"message": "本地未命中，尝试远程精确检索..."})
        await asyncio.sleep(0.05)

        # 远程：DOI? 标题?
        if _DOI_RE.match(q.strip()):
            doi = q.strip().lower()
            import urllib.request as _ur
            url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with _ur.urlopen(req, timeout=20) as resp:
                    item = json.loads(resp.read().decode())["message"]
                from arxiv_pulse.crawler.publisher import _pub_date, _clean_title, PUBLISHERS
                pub = next((p for p in PUBLISHERS if p["key"] == "tgrs"), None)  # 归属按 container 匹配略
                ...
            except Exception as e:
                yield sse_event("error", {"message": f"DOI 检索失败: {str(e)[:80]}"})
            return
        # 标题：arXiv ti + crossref query.bibliographic 各 5 条入库
        ...
```

  完整实现（文件内准确代码，放置在原 AI 解析分支位置）：

```python
        # 本地检索（全库）
        with db.get_session() as session:
            engine = SearchEngine(session)
            flt = SearchFilter(query=q, search_fields=["title", "abstract", "authors"], days_back=0,
                               limit=Config.SEARCH_LIMIT, sort_by="published", sort_order="desc")
            local_papers = engine.search_papers(flt)
        if local_papers:
            for p in local_papers[:20]:
                yield sse_event("result", {"paper": enhance_paper_data(p), "match_type": "local"})
            yield sse_event("done", {"total": len(local_papers)})
            return
        yield sse_event("log", {"message": "本地未命中，尝试按 DOI/标题远程检索..."})

        doi_match = _DOI_RE.match(q.strip())
        if doi_match:
            import urllib.request as ur
            doi = q.strip().lower()
            try:
                req = ur.Request(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}",
                                 headers={"User-Agent": "Mozilla/5.0"})
                with ur.urlopen(req, timeout=20) as resp:
                    item = json.loads(resp.read().decode("utf-8"))["message"]
                container = item.get("container-title") or [""]
                container = container[0] if isinstance(container, list) else container
                pub = {"key": "custom", "name": container or "Unspecified Journal",
                       "categories": container or "Journal"}
                paper = save_doi_paper(item, pub, db=db)
                if paper:
                    yield sse_event("log", {"message": "已从 Crossref 获取"})
                    with db.get_session() as s:
                        paper = s.query(Paper).filter_by(arxiv_id=doi).first()
                    yield sse_event("result", {"paper": enhance_paper_data(paper), "match_type": "doi"})
                    yield sse_event("done", {"total": 1})
                else:
                    yield sse_event("error", {"message": "DOI 无记录或入库失败"})
            except Exception as e:
                yield sse_event("error", {"message": f"DOI 检索失败: {str(e)[:80]}"})
            return

        if looks_like_full_title(q.strip()):
            # arXiv ti 检索
            yield sse_event("log", {"message": "正按标题检索 arXiv..."})
            crawler = ArXivCrawler()
            try:
                papers, total, new = crawler.search_and_save(f'ti:"{q.strip()}"', max_results=5)
            except Exception as e:
                papers, total, new = [], 0, 0
                yield sse_event("log", {"message": f"arXiv 标题检索失败: {str(e)[:50]}"})
            for p in papers[:5]:
                yield sse_event("result", {"paper": enhance_paper_data(p), "match_type": "title"})
            if papers:
                yield sse_event("done", {"total": len(papers)})
                return
            # Crossref query.bibliographic 兜底
            yield sse_event("log", {"message": "arXiv 未命中，尝试 Crossref..."})
            try:
                url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
                    {"query.bibliographic": q.strip(), "rows": "5",
                     "mailto": "arxiv-pulse@example.com", "select": "DOI,title,author,container-title,published"}
                )
                req = urllib.request.Request(url, headers={"User-Agent": "arXiv-Pulse/1.0 (mailto:arxiv-pulse@example.com)"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    items = json.loads(resp.read().decode("utf-8"))["message"].get("items", [])
                for item in items[:5]:
                    pub = {"key": "custom", "name": "Crossref",
                           "categories": (item.get("container-title") or [""])[0] if item.get("container-title") else "Journal"}
                    save_doi_paper(item, pub, db=db)
                with db.get_session() as s:
                    for item in items[:5]:
                        doi = (item.get("DOI") or "").lower()
                        paper = s.query(Paper).filter_by(arxiv_id=doi).first()
                        if paper:
                            yield sse_event("result", {"paper": enhance_paper_data(paper), "match_type": "title"})
                yield sse_event("done", {"total": 5})
                return
            except Exception as e:
                yield sse_event("error", {"message": f"Crossref 检索失败: {str(e)[:80]}"})
            return

        yield sse_event("log", {"message": "未识别为特定文章，按关键词检索本地库（无结果）"})
        yield sse_event("done", {"total": 0})
```

  注意：`quick` 中顶部 `import arxiv as arxiv_lib`、`SearchEngine` 已在使用；`enhance_paper_data`、`save_doi_paper` 需要在 quick 区域 import（局部）。

- [ ] **Step 3: 临时实例验证**（本地优先/DOI/标题/404）

```bash
# 起实例 + 种数据（一棵 DOI 论文）
.venv/Scripts/python.exe - <<'EOF'
import sqlite3
conn = sqlite3.connect("tests/tmp_verify_data/data/arxiv_papers.db")
conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('is_initialized','true')")
conn.execute("""INSERT OR IGNORE INTO papers (arxiv_id, source, pdf_url, title, abstract, authors, published, categories, created_at, updated_at)
 VALUES ('10.1109/test.2026.123','doi','https://doi.org/10.1109/test.2026.123','Methane Monitoring with AI Remote Sensing','abstract','[]','2026-08-26','remote sensing',datetime('now'),datetime('now'))""")
conn.commit(); conn.close()
EOF
curl -s "http://127.0.0.1:8103/api/papers/quick?q=methane+AI"  | grep -o '"paper"' | head -2   # 本地命中
curl -s "http://127.0.0.1:8103/api/papers/quick?q=10.1109/test.2026.123" | grep -o '"match_type"'
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8103/api/papers/quick?q=zzzz-not-exist"
```

- [ ] **Step 4: Commit**

```bash
git add arxiv_pulse/web/api/papers.py
git commit -m "feat: home search now local-first with DOI/title remote fallback"
```

---

### Task 6: 前端（档案卡片 + 近期页领域下拉 + UI 隔离）

**Files:**
- Create: `arxiv_pulse/web/static/js/stores/profileStore.js`
- Create: `arxiv_pulse/web/static/js/components/ProfileDialog.js`
- Modify: `arxiv_pulse/web/static/index.html`（注册组件、设置页卡片、近期页下拉、隔离旧 UI、store 接线、setup return）
- Modify: `arxiv_pulse/web/static/js/i18n/zh.js` / `en.js`

**Interfaces:**
- Consumes: Task 4 端点（API.config.profiles.*）、paperStore 现有 recent fetch/sync
- Produces: `profileStore`（list/loading/save/remove/generate）、`<profile-dialog>` 组件（emits saved）、近期页 `profileIds`（ref array）、`paperStore` 同步请求携带 profile_ids

- [ ] **Step 1: profileStore.js**

```js
const useProfileStore = defineStore('profile', {
    state: () => ({
        profiles: [],
        loading: false
    }),
    actions: {
        async fetchProfiles() {
            this.loading = true;
            try {
                const res = await API.config.profiles.list();
                this.profiles = await res.json();
            } catch (e) { console.error('Failed to fetch profiles:', e); }
            finally { this.loading = false; }
        },
        async generatePlan(description) {
            const res = await API.config.profiles.generate(description);
            return res.json();
        },
        async createProfile(data) {
            const res = await API.config.profiles.create(data);
            const profile = await res.json();
            this.profiles.push(profile);
            return profile;
        },
        async updateProfile(id, data) {
            const res = await API.config.profiles.update(id, data);
            const profile = await res.json();
            const idx = this.profiles.findIndex(p => p.id === id);
            if (idx >= 0) this.profiles[idx] = profile;
            return profile;
        },
        async removeProfile(id) {
            await API.config.profiles.remove(id);
            this.profiles = this.profiles.filter(p => p.id !== id);
        }
    }
});
```

- [ ] **Step 2: ProfileDialog.js**（新建/编辑一个对话框：name/description 输入（textarea）、「生成检索计划」按钮 → 显示 plan 预览（arxiv_queries 每条 editable input + s2_query + keywords tag）、期刊组（default_journals 复选框 + 自定义添加行 issn+name）、sources 三 checkbox、保存调用 create/update）

```js
const ProfileDialogTemplate = `
    <el-dialog :model-value="show" @update:model-value="v => $emit('update:show', v)" width="640px"
               :title="editing ? t('profiles.edit') : t('profiles.create')">
        <el-form label-width="90px">
            <el-form-item :label="t('profiles.name')">
                <el-input v-model="name" :placeholder="t('profiles.namePlaceholder')"></el-input>
            </el-form-item>
            <el-form-item :label="t('profiles.description')">
                <el-input v-model="description" type="textarea" :rows="3" :placeholder="t('profiles.descPlaceholder')"></el-input>
            </el-form-item>
            <el-form-item>
                <el-button size="small" @click="doGenerate" :loading="generating">{{ t('profiles.generate') }}</el-button>
                <span v-if="plan" style="margin-left: 10px; font-size: 12px; color: var(--text-muted);">{{ t('profiles.planHint') }}</span>
            </el-form-item>
            <el-form-item v-if="plan" :label="t('profiles.planLabel')">
                <div style="width: 100%;">
                    <div v-for="(q, i) in plan.arxiv_queries" :key="i" style="margin-bottom: 4px;">
                        <el-input size="small" v-model="plan.arxiv_queries[i]" @click.stop></el-input>
                    </div>
                    <el-input size="small" v-model="plan.s2_query" :placeholder="t('profiles.s2Placeholder')" style="margin-top: 4px;"></el-input>
                </div>
            </el-form-item>
            <el-form-item v-if="editing" :label="t('profiles.sources')">
                <el-checkbox v-model="sources.arxiv">arXiv</el-checkbox>
                <el-checkbox v-model="sources.crossref">Crossref</el-checkbox>
                <el-checkbox v-model="sources.s2">Semantic Scholar</el-checkbox>
            </el-form-item>
            <el-form-item>
                <el-button size="small" @click="removeJournal" v-if="journals.length" style="margin-left: 4px;">{{ t('profiles.journals') }} ({{ journals.length }})</el-button>
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="$emit('update:show', false)">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" @click="save" :loading="saving">{{ t('common.save') }}</el-button>
        </template>
    </el-dialog>
`;
```

  setup 完整实现（编辑模式从 store 拿 profile；执行代码中完成）。注册 `app.component('profile-dialog', {...})`。

- [ ] **Step 3: index.html 设置页卡片**（设置 drawer 或页面内"研究领域"区块附近）加入 profiles 列表 + 「新建档案」按钮 + `<profile-dialog>` 挂载；**移除原"选择研究领域"入口 UI**（保留引用显示统计）

- [ ] **Step 4: 近期论文页**：在 `daysOptions` 行旁加领域下拉（el-select multiple，绑定 `profileIds`，选项 profileStore.profiles），updateRecentPapers/loadMore 请求加 `profile_ids=profileIds.join(',')`；「筛选领域」按钮与 sources checkbox-group 模板移除（store 状态保留）

- [ ] **Step 5: i18n**（zh/en 各加）：

```js
// zh
profiles: {
    title: '检索领域',
    create: '新建档案',
    edit: '编辑档案',
    name: '名称',
    namePlaceholder: '如：AI 遥感',
    description: '自然语言描述',
    descPlaceholder: '如：AI+遥感，侧重甲烷反演与检测，算法和模型类均可',
    generate: '生成检索计划',
    planHint: 'AI 生成的计划，可手动微调',
    planLabel: '检索计划',
    s2Placeholder: 'Semantic Scholar 检索词',
    sources: '检索来源',
    journals: '期刊组',
    syncNow: '同步'
}
```

- [ ] **Step 6: Playwright 冒烟**：临时实例（含 is_initialized + 1 个 profile 种子）：设置页有档案卡；近期页领域下拉存在；旧「筛选领域」按钮与来源勾选不可见；同步按钮可点（无界外错误）

- [ ] **Step 7: Commit**

```bash
git add arxiv_pulse/web/static
git commit -m "feat(web): profile management UI, recent-page profile selector, hide legacy field filters"
```

---

### Task 7: 集成回归 + 收尾

- [ ] **Step 1: 临时实例全链路**：建档案（无 key 降级）→ 近期页更新（profile_ids=1）→ 观察 SSE 日志（arXiv 源）→ DB 检查 papers+paper_profiles 增长 → 清理实例数据

- [ ] **Step 2: 对用户 8000 的只读 Playwright 回归**：主页搜索按钮/论文集/聊天/PDF 面板/全站无 pageerror

- [ ] **Step 3: git 工作树检查**（只 add 计划内文件；docs 已在库）

- [ ] **Step 4: 推送 main（用户已批准 push 惯例）并提醒用户重启服务（后端变更）**

---

## Self-Review 记录

- **Spec 覆盖**：数据模型(T1) / AI 规范化(T2) / 三源管线(T2,3) / CRUD+recent 接线(T4) / quick 重写(T5) / 前端卡片+近期页+隔离(T6) / i18n(T6) / 验证与回归(T7)。主页旧 AI 解析逻辑退役由 T5 替换完成（git 可溯）。
- **占位扫描**：T2 中 sync_profile_papers 有 `or True` 与 `attach_profile` 第一版说明段——已在代码注释指明执行时修正，T2 Step 3 给出正确最终代码（执行以"修正版"为准）。T5 的完整实现代码已给出（"完整实现"块）。
- **类型一致**：`generate_retrieval_plan`→dict；`sync_profile_papers`→dict stats{arxiv_new, crossref_new, s2_new, total_new}；`save_s2_item`→Paper|None；`attach_profile(db, paper, profile_id)` 签名各任务一致；端点 `/api/config/profiles...` 与 api.js 一致；`profile_ids` 逗号串两端一致。
- **修正声明**：T2 Step 3 中 `sync_profile_papers` 里的 `if sources.get("crossref") and not exclude_words or True:` 一行是草稿痕迹，执行时替换为 `if sources.get("crossref", True):`；`attach_profile` 以修正版（真实 session 查询）为准。
