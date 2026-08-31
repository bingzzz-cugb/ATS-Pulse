# 功能 2 设计：内置 PDF 查看器「原文」浮窗 + AI 助手联动

日期：2026-08-31
状态：已批准（待实现）

## 背景

AI 助手在分析论文时会在后台下载 PDF、解析全文后即删除（全文存入 `paper_content_cache` 表），用户无法在本地直接查看论文原文。用户希望读论文和问 AI 同时进行：在 AI 助手浮窗旁边打开一个 PDF 阅读窗口，且可最大化沉浸式阅读。

## 目标

1. AI 助手浮窗顶部新增「原文」按钮，点击后在助手浮窗**左侧贴合**弹出 PDF 阅读浮窗，展示当前选中论文的 PDF。
2. PDF 浮窗与助手浮窗**联动拖拽**：拖任意一个，两个一起移动，相对位置保持不变。
3. PDF 浮窗支持**最大化/还原**（铺满全屏，带动画）；最大化期间助手浮窗仍可呼出（z-index 高于 PDF），边读边问。
4. PDF 浮窗头部支持在**多篇选中论文**间切换（下拉选择）。
5. PDF 文件**本地缓存**到数据目录，避免重复下载；二次打开秒开。

## 非目标（YAGNI）

- 不引入 pdf.js，使用 iframe + 浏览器内置 PDF 查看器（Chrome/Edge 原生支持缩放、页码、搜索）。
- 不做页面级标注/高亮/书签。
- 不改动论文卡片上的「PDF」按钮行为（保持新标签打开外链）。
- chat.py 现有的"下载→临时文件→解析→删除"流程保持不变（已验证稳定；后续可复用 pdf_service）。

## 后端设计

### 新端点 `GET /api/papers/{arxiv_id}/pdf`

放于 `arxiv_pulse/web/api/papers.py`：

1. 查询 DB 中的 Paper 记录（`arxiv_id` 唯一索引），不存在 → 404。
2. 本地缓存检查：`{Config.DATA_DIR}/pdfs/{arxiv_id}.pdf` 存在 → 直接 `FileResponse`。
3. 不存在则按来源下载：
   - `source == 'arxiv'`（默认）：从 `https://arxiv.org/pdf/{arxiv_id}.pdf` 下载。
     - 成功 → 写入缓存文件（若 `pdfs/` 目录不存在则 `makedirs`），返回 `FileResponse`。
     - 失败（非 200 / 网络异常 / 429）→ `HTTPException(502, "PDF 下载失败")`。
   - 其他来源（`source == 'doi'`，如 TGRS/Science）：`RedirectResponse` 302 到 `paper.pdf_url`，下载交给浏览器（出版商反爬，本地代理不可靠）。
4. 响应头：`Content-Type: application/pdf`，提示浏览器内嵌显示（`Content-Disposition: inline`）。

### 新文件 `arxiv_pulse/services/pdf_service.py`

- `pdf_cache_path(arxiv_id) -> Path`：`{Config.DATA_DIR}/pdfs/{arxiv_id}.pdf`
- `get_or_download_pdf(arxiv_id) -> tuple[bytes|None, int]`（成功返回内容与状态码；仅 arxiv 来源）：
  - 下载逻辑复制 chat.py 的 UA（`Mozilla/5.0`）+ `timeout=60`。
- papers.py 端点调用该服务；chat.py 不重构。

### 路由注册

确认 `papers.py` 路由已挂载于 `/api/papers`（现有 `/papers/{arxiv_id}/content` 同前缀），新端点为 `/api/papers/{arxiv_id}/pdf`，自动生效。

## 前端设计

### 1. 「原文」按钮（ChatWidget.js）

- 位置：`chat-header` 内标题右侧、新建对话按钮之前。
- 图标：文档/文件图标（16px），`el-button text` 风格，与现有 header 按钮一致。
- 行为：`@click.stop`，有选中论文（`selectedChatPapers.length > 0`）时 **emit `open-pdf`**；无选中论文时禁用置灰（title 提示"先选择论文"）。
- 该按钮由主应用（index.html）监听 `open-pdf` 后统一处理，ChatWidget 不持有 pdf 状态。

### 2. PDF 浮窗（新组件 `PaperPdfPanel.js`）

镜像 chat-window 的浮窗结构（header + body + 拖拽把手 + resize 把手），props：

- `show`、`position`、`size`、`zIndex`、`fullscreen`、`animating`、`currentLang`、`papers`（选中论文列表）、`currentArxivId`
- emits：`update:show`、`update:fullscreen`、`update:current`（切换论文）、`bring-to-front`、`start-drag`、`start-resize`、`open-external`

Header 内容（从左到右）：

1. 论文切换下拉（el-select）：选项为已选论文（显示标题截断/arXiv ID），绑定 `currentArxivId`；选中变化 emit `update:current`。
2. 「新标签打开」按钮：`window.open` 后端 PDF 端点或外部 pdf_url（emits `open-external`）。
3. 「最大化 / 还原」按钮：switch `fullscreen`（带 `animate-fullscreen` 动画，样式复用 chat 的动画类思路）。
4. 「关闭」按钮：emit `update:show false`。

Body：

- `<iframe :src="'/api/papers/' + currentArxivId + '/pdf'">`，浏览器内置 PDF 查看器渲染。
- 加载失败无法直接侦测（跨 iframe），由后端 502/404 时在面板内显示错误占位：**错误时用 `@load` 判定？不可靠** —— 采用简捷方案：面板保留「新标签打开」和「在 arXiv 打开」兜底按钮；后端 404/502 时 iframe 显示浏览器错误页，用户点兜底按钮即可。可选后续优化。
  - 说明：主要场景（arxiv 源 + 缓存命中）都稳定，失败兜底按钮足够。

### 3. 联动拖拽模型（index.html，核心）

状态：

- `pdfExpanded = ref(false)`
- `pdfSize = ref({ width: 620, height: 720 })` （打开时按视口收敛：`width = min(620, viewport*0.4)`, `height = min(720, viewport*0.8)`）
- `pdfFullscreen = ref(false)`、`pdfAnimating = ref(false)`
- `pdfZIndex = ref(low 初始值，进入 bringToFront 栈)`
- **偏移模型**：`pdfOffset = ref({ dx: -, dy: 0 })` —— PDF 相对 chat 的偏移
  - `pdfPosition` 为 **computed**：`{ x: chatPosition.x + pdfOffset.dx, y: chatPosition.y + pdfOffset.dy }`
- `currentPdfArxivId = ref('')` —— 当前展示的论文 id

打开逻辑（监听 ChatWidget `open-pdf`）：

- `currentPdfArxivId = selectedChatPapers[0].arxiv_id`（若重复点击且已打开则不重置）
- 计算贴合位置：`pdfOffset = { dx: -(pdfSize.width + 12), dy: 0 }`（紧贴 chat 左侧）
- 视口自适应：若 chat.x - pdf.width - 12 < 0，则 dx 取 `-(chat.x - 12)`（右对齐 chat 左缘）或包到右侧：`dx = chat.width + 12`？—— 取与 chat 右缘贴合或左缘贴合中不越界的一侧：**先尝试左侧，越界则放右侧**（`dx = chatSize.width + 12`）。
- `pdfExpanded = true`，bringToFront('pdf')

拖拽（两个面板共用一套逻辑，实现"拖任一个两个一起走"）：

- `startDragChat`（已有）：`dragTarget = 'chat'`，onDrag 更新 `chatPosition` → **`pdfPosition` 为 computed，自动跟随**。
- `startDragPdf`（新增）：`dragTarget = 'pdf'`：
  - 记 `dragOffset = { x: e.clientX - pdfPosition.x, y: e.clientY - pdfPosition.y }`
  - onDrag 中：`delta = { x: (e.clientX - dragOffset.x) - pdfPosition.x, y: (e.clientY - dragOffset.y) - pdfPosition.y }` → `chatPosition.value = { x: chatPosition.x + delta.x, y: chatPosition.y + delta.y }`（**平移组基准 chatPosition + 缩放边界处理**）
  - 即：往 PDF 的位移等价作用于 chatPosition；`pdfOffset` 不变 → 两窗相对位置恒定，一起移动。
- clamp：沿用现有 chat 的 clamp（视口内）；PDF 允许轻微越界，用户一般拖不出去。
- 缩放：`startResizePdf` 只改 `pdfSize`，不动 offset（保持左上角锚点），**仅缩放时两窗不联动**（需求只要求拖动联动）。

最大化：

- `togglePdfFullscreen()`：翻转 `pdfFullscreen` + 300ms `pdfAnimating` 动画（镜像 toggleChatFullscreen）。
- fullscreen 时忽略 position：`:style="fullscreen ? { zIndex: fsZ } : fixed..."`，其中 **`fsZ = max(cart/chat/detail/collectionDetail 当前 zIndex) - 1`**（动态计算，保证助手浮窗、其他浮窗、FAB 都可在 PDF 之上常驻/呼出）。
- 还原后回 computed 位置（天然原位）。

置顶与其他：

- `bringToFront` 增加 `'pdf'` 分支（纳入 zIndex 栈，抢 Z 时与 chat 独立竞争 —— 点击 pdf 面板置顶 pdf，这通常与联动拖拽同时发生，互不冲突）。
- Esc 关闭优先级数组加入 pdf 面板（排在 chat 之后的顺序；按现有逻辑：zIndex 最高者先关）。
- 关闭 PDF 浮窗（X）：`pdfExpanded = false`；此后 chat 自由拖；再次点「原文」→ 重新计算贴合 offset。
- 重置对话/清空选中论文（selectedChatPapers 变为空）时：若 PDF 打开则以当前 `currentPdfArxivId` 继续展示（不强制关闭，论文可能仍有效）；`currentPdfArxivId` 若已不在选中列表中，下拉仍显示该值（保持最后一个），切换列表为空时下拉禁用。

### 4. 样式与 i18n

- `main.css`：`.pdf-window` 一族样式（镜像 `.chat-window`）：header、body、fullscreen 状态、`.resize-handle`、动画 `animate-fullscreen`/`panel` transition 复用。
- i18n（zh.js / en.js）：
  - `paper.original`: '原文' / 'Original'
  - `paper.openExternal`: '新标签打开' / 'Open in new tab'
  - `paper.openArxiv`: '在 arXiv 打开' / 'Open on arXiv'
  - `paper.noSelection`: '请先选择论文' / 'Select a paper first'
  - `pdf.loading`: 'PDF 加载中…' / 'Loading PDF…'
  - `pdf.loadFailed`: 'PDF 加载失败' / 'Failed to load PDF'

### 5. 涉及文件

| 文件 | 更改 |
|---|---|
| `arxiv_pulse/services/pdf_service.py` | 新增：缓存路径 + 下载 |
| `arxiv_pulse/web/api/papers.py` | 新增端点 `/api/papers/{arxiv_id}/pdf` |
| `arxiv_pulse/web/static/js/components/PaperPdfPanel.js` | 新增组件（模板字符串 + setup） |
| `arxiv_pulse/web/static/js/components/ChatWidget.js` | header 加「原文」按钮 + emits |
| `arxiv_pulse/web/static/index.html` | pdf 状态/拖拽/bringToFront/Esc/挂载 `<paper-pdf-panel>` |
| `arxiv_pulse/web/static/css/main.css` | pdf-window 样式 |
| `arxiv_pulse/web/static/js/i18n/zh.js` / `en.js` | 新增文案 |

## 边界与行为约定

- **arxiv 下载失败（429/网络）**：后端 502 → iframe 报错页 → 用户点「新标签打开」/「在 arXiv 打开」兜底。
- **非 arxiv 论文（TGRS/Science）**：端点 302 到外部 pdf_url；外部站点若禁止 iframe 嵌入（X-Frame-Options），用户用「新标签打开」。
- **多篇选中**：默认显示第一篇；下拉可切换；再次下载缓存不重复。
- **动画时长**：与 chat 全屏动画一致（300ms）。

## 验证清单

1. 后端：`curl /api/papers/{id}/pdf` 首次 200 + Content-Type pdf；二次 200 且 mtime 不变（命中缓存）；不存在 id → 404。
2. 前端（Playwright，只读验证）：
   - 点「分析」→ chat 浮窗出现 → 点「原文」→ PDF 浮窗贴合出现在 chat 左侧，iframe 加载出 PDF。
   - 拖 chat → PDF 同步移动；拖 PDF → chat 同步移动；相对位置不变。
   - 最大化合集：PDF 铺满、点 chat FAB 助手仍可显示在其上方；还原后回到原位。
   - 选中 2 篇论文 → 下拉切换 → iframe src 变化。
   - 关闭 PDF → chat 独立拖动；重开 → 重新贴合。
3. 无控制台错误，无 Vue 模板编译错误（注意：模板中不用自闭合非 void 元素）。
