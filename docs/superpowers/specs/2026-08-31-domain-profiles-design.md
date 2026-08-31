# 设计：领域档案检索（多源）与主页搜索重构

日期：2026-08-31
状态：待用户 review

## 背景与目标

ATS 的核心日常动线是"每天检索当天研究的领域进展，直接学习"。现状：近期论文页按**硬编码 arXiv 分类**（+TGRS/Science 两期刊）同步，领域无法自定义为自然语言主题（如"AI+遥感甲烷反演"），也无法覆盖跨来源（会议/期刊/预印本）的当日论文；同时主页搜索在做"AI 解析+远程批量搜"与近期页功能重叠。

目标：
1. 用户用**自然语言定义检索领域**（档案），AI 将其规范化为结构化检索计划
2. 同步按档案执行，多来源尽力覆盖当日/指定范围论文（arXiv + 期刊组 Crossref + Semantic Scholar），自动去重入库
3. 主页搜索重构为"本地库检索 + 特定文章（arXiv ID / DOI / 标题）远程抓取"
4. 界面行为：近期论文页简化为一选领域 + 时间 + 更新；旧字段选择器等 UI 隔离（代码保留不删）

## 非目标

- 定时/自动每日同步（保持手动，用户已确认）
- 向量检索 / 语义索引（YAGNI）
- 自动周报/摘要推送
- 云端同步/多机部署
- 删除被隔离的旧 UI 代码（后续再决定）

## 数据模型（新）

### `research_profiles`（领域档案）
| 列 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| name | str | 档案名（"AI 遥感"） |
| description | str | 用户自然语言描述 |
| retrieval_plan | Text(JSON) | `{arxiv_queries: [str], s2_query: str, keywords: [str], exclude_words: [str]}` |
| journals | Text(JSON) | `[{key, name, issn, enabled}]`（预置模板 + 自定义） |
| sources | Text(JSON) | `{arxiv: bool, crossref: bool, s2: bool}`（默认全 true） |
| enabled | bool | |
| updated_at | datetime | |

### `paper_profiles`（论文↔领域 多对多）
`profile_id, paper_id` 联合唯一。论文可属多个档案。

### 复用现有
`papers` 表（`source` arxiv/doi 区分）、`sync_tasks`（进度/日志）、`system_config`（search_queries 保留供旧逻辑，新同步用档案 plan）。

## AI 规范化服务（`services/profile_service.py`）

`generate_retrieval_plan(description) -> plan JSON`：
- 调用 AI 一次（非流式，max_tokens~1500，temperature 0.2）
- 提示模板要求输出 JSON：arxiv_queries（2-3 条，用 arXiv 语法 AND/OR/引号）、s2_query、keywords、exclude_words、suggested_journals（从预置模板 + 常见开源遥感/AI 期刊中选）
- 校验：JSON 解析失败或无 key → 降级：`arxiv_queries=[description]`，`s2_query=description`，其余空，仍可建档/编辑（标记"待 AI 生成"）
- 提供"重新生成"按钮（覆盖现有 plan）

## 检索与同步管线

`sync_profile(profile_id, date_from, date_to)`（复用 `update_recent_papers` 上下文，SSE 日志沿用）：

1. **arXiv**（sources.arxiv）：对 plan.arxiv_queries 每条约 30 篇（`search_and_save(query, max_results=30)`，用现有 submittedDate 范围参数）——复用现有 date range 逻辑，不再依赖 recent_papers_limit
2. **Crossref 期刊组**（sources.crossref）：对每个 enabled journal 的 ISSN 调 `fetch_crossref_items(issn, date_from, date_to)` 复用现有函数（不再依赖 days_back 参数），逐条 `save_doi_paper`（已有）
3. **Semantic Scholar**（sources.s2）：新增 `search_s2_items(query, date_from, date_to, rows=25)`（`/graph/v1/paper/search?query=&fields=...&publicationDateOrYear=YYYY-MM-DD,YYYY-MM-DD`），S2 命中论文入库：提取 `externalIds.ArXiv` / DOI → 走现有去重（arxiv_id 唯一）
4. 每源结束 yield 日志："arXiv 新增 X / 期刊新增 Y（共 Z 篇）/ S2 新增 W 篇"
5. **去重**：papers.arxiv_id 唯一列天然去重（doi 论文 arxiv_id=doi）；S2 的 arXiv 命中与 arXiv 源命中自动合流
6. 入库时打 `paper_profiles` 关联

## 前端改动

### 设置页：新增「检索领域」卡片
- 档案列表：名称 / enabled 开关 / 来源摘要（arXiv/期刊 n 本/S2）/ 期刊组数 / 编辑/删除/新建
- 新建/编辑对话框：
  - 名称、自然语言描述（输入框）
  - 「生成检索计划」按钮 → 调用 AI → 可编辑预览（arXiv 查询串逐条可改）
  - 期刊组：预置模板（TGRS、Science）勾选 + 自定义 ISSN/名称添加行
  - 来源开关：arXiv / CrossRef 期刊 / Semantic Scholar 三个 checkbox
- 每次档案变更不触发同步；同步在近期页按所选档案执行

### 近期论文页
- 顶部控件：领域下拉（多选合并，默认最近使用）/ 时间范围（现有）/ 更新按钮
- **UI 隔离**（代码保留不删）：原「筛选领域」按钮（FieldSelectorDialog 入口）、设置里的研究字段选择器、近期页来源勾选（recentSources checkbox-group 及其 watch）均从模板移除/隐藏；对应 store 状态、后端参数（cats/sources）保留不使用
- 领域下拉联动 `paper_profiles` 展示领域徽标（可选：论文卡片右上角小标签——放在 page 顶端统计即可，YAGNI 先不做卡片徽标）

### 主页搜索重构（`/api/papers/quick`）
- 解析逻辑：q 匹配 arXiv ID（现有 parse_arxiv_id）→ **DOI**（正则 `10\.\d{4,9}/[-._;()/:A-Z0-9]+`）→ **疑似完整标题**（长度>15 且含空格，若本地标题模糊命中率触发）；否则按**本地检索**处理
- 本地优先路径：
  - ID/DOI/标题 → 查库（arxiv_id / doi 字段 / title ILIKE 前缀短语）→ 有 → 返回（summarized 缺则补总结，同现有）
  - 无 → 远程：arXiv ID：既有 `fetch_paper_by_id`；DOI：`https://api.crossref.org/works/{doi}` → save_doi_paper（期刊归属按 container-title 匹配预置模板，否则 journal_ref=container）；标题：arXiv `ti:"..."` 检索 + crossref `query.bibliographic` 各取前 5 篇，展示候选列表（不逐篇入库，用户点选后入库）？—— **决策：标题远程命中后逐篇入库并展示（与 ID 行为一致，简单一致）**，上限每源 5 篇
  - 本地检索（关键词/自然语言）：仅对**全库** SearchEngine 检索（title/abstract/authors），无 AI 消耗，输出顺序 relevance 排序（现有 sort_papers_by_relevance）
- 移除：旧 AI 解析查询 + arXiv 远程批量搜索（该能力已由档案同步覆盖，重复逻辑从 endpoint 删除，git 历史可溯）

### i18n
- 新增：profiles.*（管理/新建/描述/生成计划/来源/期刊组等约 20 键，zh/en）

## 成本与预期

- 每档案每日同步 ≈ arXiv 2-3 查询 + 期刊 1-5 ISSN + S2 1 次 ≈ 5-10 秒、~10 个 HTTP 请求、**0 次 AI 调用**（AI 仅建档/重新生成时每次 1 次）
- S2 无 key 限流对本场景（每日 ≤2-3 次/档案）无压力；必要时退避重试沿用 S2 现有 fetch_s2_abstract 的退避模式
- 同步结果 ≈ 用户领域当日全网 20-60 篇（AI+遥感核心圈），30 篇展示上限由 recent_papers_limit 控制

## 涉及文件

- `arxiv_pulse/models/`：+2 表（research_profiles, paper_profiles）
- `arxiv_pulse/services/profile_service.py`：新（AI 规范化 + 检索/入库 helper）
- `arxiv_pulse/crawler/s2.py`：新（search_s2_items + S2 item→paper 入库；复用 publisher.save_doi_paper 逻辑扩展）
- `arxiv_pulse/web/api/papers.py`：quick 端点重写（本地优先）；recent/update 接 profile 并行同步
- `arxiv_pulse/web/api/config.py`：profiles CRUD 端点
- 前端：`js/services/api.js`、`js/stores/*`（profileStore 新）、`index.html`（设置卡 + 近期页 + 主页）、`js/components/ProfileDialog.js` 新、i18n zh/en
- 隔离清单（不删）：FieldSelectorDialog.js、recentSources/cats 相关逻辑

## 验证清单

1. 后端单测/手动：
   - 建档案（有 AI key）→ plan JSON 结构正确；无 key → 降级可用
   - sync_profile：三源各自日志与新增数；同论文 arXiv/S2 重复不重复入库
   - 期刊组自定义 ISSN 生效（用 TGRS 实测）
   - 主页：DOI / arXiv ID / 标题三个路径在临时库（有/无记录）行为正确；本地检索命中库内 TGRS 论文
2. 前端（Playwright）：
   - 设置页档案 CRUD + 生成计划预览
   - 近期页：领域下拉切换/多选 → 同步 → 列表出现跨源论文；源勾选/筛选领域按钮不可见（隔离）；老逻辑仍可用（代码级）
   - 主页搜索：自然语言 → 本地结果；DOI → 远程抓回
3. 回归：现有近期/主页/文集/聊天/PDF 面板不回归
