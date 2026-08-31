# PDF 原文浮窗 + 联动拖拽 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 助手浮窗左侧贴合新增一个内置 PDF 阅读浮窗（「原文」按钮打开），拖任一个浮窗两个一起走，支持全屏沉浸式阅读与多篇论文切换。

**Architecture:** 后端新增 `GET /api/papers/{arxiv_id}/pdf`（arXiv 源下载并缓存到 `{DATA_DIR}/pdfs/`，DOI 源 302 到外部 pdf_url）；前端新增 `PaperPdfPanel` 浮窗组件，`pdfPosition` 用 computed（= `chatPosition + pdfOffset`）实现拖拽联动；ChatWidget 标题栏加「原文」按钮。

**Tech Stack:** FastAPI + SQLite + 原生 JS 字符串模板（Vue 3 全量 CDN、Pinia、Element Plus），Playwright（.venv 已有 playwright，无 pytest）。

**Spec:** `docs/superpowers/specs/2026-08-31-pdf-reader-original-panel-design.md`

## Global Constraints

- 本目录是 git 仓库（根 = `D:/hello/Arxiv_reading/ArXiv-Pulse`），但工作区已有**未提交改动**（lock.py、papers.py 等，属于之前功能），commit 时**只 add 本计划涉及的文件**，绝不 `git add -A`。
- 用户实例运行在 8000 端口（PID 未知，勿杀勿动）；验证一律用 `tests/tmp_verify_data` 临时数据目录 + 端口 8103 起独立实例（`pulse serve tests/tmp_verify_data -f --port 8103`）。
- `.venv/Scripts/python.exe` 有 playwright（用 chromium-1223 路径 `C:\Users\MECHREVO\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe`），无 pytest。验证脚本写完即删，不进仓库。
- Vue 模板：`#app` 内联模板走浏览器编译，**任何元素禁止自闭合 `/>`**（非 void 元素），成对书写。已有教训：自闭合吞掉兄弟节点。
- 模板只能访问 setup() 返回的变量 —— 新状态必须加进 setup 的 `return` 对象。
- 前端文件为静态文件，改完刷新浏览器即可，无需重启后端（端点除外）。

---

### Task 1: 后端 PDF 端点 + 缓存服务

**Files:**
- Create: `arxiv_pulse/services/pdf_service.py`
- Modify: `arxiv_pulse/web/api/papers.py`（文件底部追加端点；顶部 import 已含 `FileResponse`? 需检查 —— 若无则加 `from fastapi.responses import FileResponse, RedirectResponse, Response`）
- Test: 临时 `/tmp/pdf_server_check.py`（不入库，验证后删）

**Interfaces:**
- Consumes: `Config.DATA_DIR`（`arxiv_pulse/core/config.py`，str 类型，数据目录如 `D:\...\pulse-data\data`）、`Paper` 模型（字段 `arxiv_id`、`source`、`pdf_url`）、`get_db()`（`arxiv_pulse.web.dependencies`）
- Produces:
  - `pdf_cache_path(arxiv_id: str) -> Path`
  - `get_or_download_arxiv_pdf(arxiv_id: str) -> bytes | None`
  - 端点 `GET /api/papers/{arxiv_id}/pdf` → 200 `application/pdf`（缓存命中或下载成功）/ 302（doi 且含 pdf_url）/ 404 / 502

- [ ] **Step 1: 写 pdf_service.py**

```python
"""PMT: arXiv PDF 下载缓存服务"""
import requests
from pathlib import Path

from arxiv_pulse.core import Config


def pdf_cache_path(arxiv_id: str) -> Path:
    return Path(Config.DATA_DIR) / "pdfs" / f"{arxiv_id}.pdf"


def get_or_download_arxiv_pdf(arxiv_id: str) -> bytes | None:
    """返回缓存或新下载的 PDF 内容；失败返回 None（仅 arXiv 源）"""
    cache = pdf_cache_path(arxiv_id)
    if cache.exists():
        return cache.read_bytes()
    resp = requests.get(
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    if resp.status_code != 200:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(resp.content)
    return resp.content
```

- [ ] **Step 2: 在 papers.py 末尾加端点**

```python
@router.get("/{arxiv_id}/pdf")
async def get_paper_pdf(arxiv_id: str):
    """获取论文 PDF（arxiv 源本地缓存；doi 源跳转外部链接）"""
    from arxiv_pulse.services.pdf_service import get_or_download_arxiv_pdf, pdf_cache_path
    from fastapi.responses import RedirectResponse, Response

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
            return RedirectResponse(paper.pdf_url)
        raise HTTPException(status_code=404, detail="No PDF URL available")

    data = get_or_download_arxiv_pdf(arxiv_id)
    if data is None:
        raise HTTPException(status_code=502, detail="PDF download failed")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )
```

  同时在 papers.py 顶部 import 补 `FileResponse`（若无），`Response`/`RedirectResponse` 已在函数内 import 亦可（保持函数内 import，与文件现有风格一致时优先文件风格）。

- [ ] **Step 3: 起临时实例验证（首次下载 + 缓存命中 + 404/302）**

```bash
cd D:/hello/Arxiv_reading/ArXiv-Pulse
mkdir -p tests/tmp_verify_data
.venv/Scripts/pulse.exe serve tests/tmp_verify_data -f --port 8103 &   # 后台；或另开终端
```

  种一条记录到临时 DB（用仓库 root 的 sqlite3 手动 insert 或直接 curl 前先临时用 python 脚本 insert）：

```python
# /tmp/_seed.py —— 用 .venv python 执行，插入 arXiv 论文 + 一篇 doi 论文
import sqlite3
conn = sqlite3.connect("tests/tmp_verify_data/data/arxiv_papers.db")
conn.execute("""INSERT OR IGNORE INTO papers (arxiv_id, source, pdf_url, title, abstract, authors, published, categories, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
             ("2608.26820", "arxiv", "https://arxiv.org/pdf/2608.26820.pdf", "t", "a", "[]", "2026-08-27", "cs.CV", "2026-08-27 00:00:00", "2026-08-27 00:00:00"))
# arXiv ID 2608.26820 已知真实存在（用户库中同 ID）；若 502 表明 arXiv 拉取受限，换任意库里存在的 ID 均可 —— 但临时库只有一条
conn.commit(); conn.close()
```

  实际步骤（替换上面提示中的伪代码，直接执行）：

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:8103/api/papers/2608.26820/pdf   # 期望：200 application/pdf，且 tests/tmp_verify_data/data/pdfs/2608.26820.pdf 出现
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8103/api/papers/9999.99999/pdf                  # 期望 404
```

  缓存命中：`ls -l` 记录 mtime，再次 curl，mtime 不变。

- [ ] **Step 4: 停掉临时实例、清理临时目录**

```bash
.venv/Scripts/pulse.exe stop tests/tmp_verify_data
rm -rf tests/tmp_verify_data /tmp/_seed.py
```

- [ ] **Step 5: Commit**

```bash
git add arxiv_pulse/services/pdf_service.py arxiv_pulse/web/api/papers.py
git commit -m "feat: add paper PDF proxy endpoint with local cache"
```

---

### Task 2: i18n 文案（zh/en）

**Files:**
- Modify: `arxiv_pulse/web/static/js/i18n/zh.js`（`paper` 段落，最后一个键 `removeFromCollection` 之后加）
- Modify: `arxiv_pulse/web/static/js/i18n/en.js`（`paper` 段落，同位置）

**Interfaces:**
- Produces: `t('paper.original')`、`t('paper.openExternal')`、`t('paper.openArxiv')`、`t('paper.noSelection')`、`t('pdf.loading')`、`t('pdf.loadFailed')` —— 供 Task 3/4 使用。

- [ ] **Step 1: zh.js 加入**

```js
        original: '原文',
        openExternal: '新标签打开',
        openArxiv: '在 arXiv 打开',
        noSelection: '请先在论文列表中选中论文',
```

  并在文件末尾 `paper` 段后 / `time` 段前新增：

```js
    pdf: {
        loading: 'PDF 加载中...',
        loadFailed: 'PDF 加载失败，请尝试在新标签中打开'
    },
```

- [ ] **Step 2: en.js 加入**

```js
        original: 'Original',
        openExternal: 'Open in new tab',
        openArxiv: 'Open on arXiv',
        noSelection: 'Select papers first',
```

```js
    pdf: {
        loading: 'Loading PDF...',
        loadFailed: 'Failed to load PDF. Try opening it in a new tab.'
    },
```

- [ ] **Step 3: 快速冒烟**

```bash
node -e "const z=require('fs').readFileSync('arxiv_pulse/web/static/js/i18n/zh.js','utf8'); new Function(z.replace('const i18nZh','var i18nZh')+';return i18nZh.paper.original&&i18nZh.pdf.loading'); console.log('ok')"
```

  或直接浏览器刷新看设置页语言切换不报错（全局语法错误会白屏）。

- [ ] **Step 4: Commit**

```bash
git add arxiv_pulse/web/static/js/i18n/zh.js arxiv_pulse/web/static/js/i18n/en.js
git commit -m "feat(i18n): add original-pdf panel strings"
```

---

### Task 3: PaperPdfPanel 组件 + 样式

**Files:**
- Create: `arxiv_pulse/web/static/js/components/PaperPdfPanel.js`
- Modify: `arxiv_pulse/web/static/css/main.css`（末尾追加 `.pdf-window` 一族样式）
- Modify: `arxiv_pulse/web/static/index.html`（在 `ChatWidget.js` 之后加 `<script src="js/components/PaperPdfPanel.js"></script>`）

**Interfaces:**
- Consumes: props `show/position/size/zIndex/fullscreen/animating/currentLang/papers/currentArxivId`；emits `update:show/update:fullscreen/update:current/bring-to-front/start-drag/start-resize/open-external`。`papers` 为 `[{arxiv_id, title}]`。
- Produces: `<paper-pdf-panel>` 全局组件（字符串模板 `const PaperPdfPanelTemplate` + `app.component('paper-pdf-panel', {...})`）。

- [ ] **Step 1: 写组件文件**

```js
const PaperPdfPanelTemplate = `
    <transition name="panel">
        <div v-if="show"
             class="chat-window pdf-window"
             :class="{ fullscreen: fullscreen, 'animate-fullscreen': animating }"
             :style="fullscreen ? { zIndex: zIndex } : { position: 'fixed', left: position.x + 'px', top: position.y + 'px', width: size.width + 'px', height: size.height + 'px', zIndex: zIndex }"
             @mousedown="onMouseDown"
             @click="$emit('bring-to-front')">
            <div class="chat-header">
                <span class="chat-title">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                        <path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>
                    </svg>
                    {{ t('paper.original') }}
                </span>
                <div class="chat-header-actions">
                    <el-select v-model="currentPaper" size="small" style="width: 180px; margin-right: 8px;" placeholder="{{ t('paper.original') }}">
                        <el-option v-for="p in papers" :key="p.arxiv_id" :label="shortTitle(p)" :value="p.arxiv_id"></el-option>
                    </el-select>
                    <el-button text @click.stop="$emit('open-external')" :title="t('paper.openExternal')">
                        <el-icon><Link /></el-icon>
                    </el-button>
                    <el-button text @click.stop="toggleFullscreen" :title="fullscreen ? (currentLang === 'zh' ? '还原' : 'Restore') : (currentLang === 'zh' ? '全屏' : 'Fullscreen')">
                        <el-icon><component :is="fullscreen ? 'FullScreen' : 'ScaleToOriginal'" /></el-icon>
                    </el-button>
                    <div class="collapse-btn" @click.stop="$emit('update:show', false)" :title="currentLang === 'zh' ? '关闭' : 'Close'">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                    </div>
                </div>
            </div>
            <div class="pdf-body">
                <iframe v-if="currentArxivId" :key="currentArxivId" style="width:100%;height:100%;border:none;" :src="pdfSrc"></iframe>
                <div v-else class="pdf-empty">{{ t('paper.noSelection') }}</div>
            </div>
            <div class="resize-handle"></div>
        </div>
    </transition>
`;

const PaperPdfPanel = {
    template: PaperPdfPanelTemplate,
    props: {
        show: Boolean, position: Object, size: Object, zIndex: Number,
        fullscreen: Boolean, animating: Boolean, currentLang: String,
        papers: { type: Array, default: () => [] },
        currentArxivId: { type: String, default: '' }
    },
    emits: ['update:show', 'update:fullscreen', 'update:current', 'bring-to-front', 'start-drag', 'start-resize', 'open-external'],
    setup(props, { emit }) {
        const pdfSrc = Vue.computed(() => `/api/papers/${props.currentArxivId}/pdf`);
        const currentPaper = Vue.computed({
            get: () => props.currentArxivId,
            set: (v) => emit('update:current', v)
        });
        const shortTitle = (p) => {
            if (!p || !p.title) return p ? p.arxiv_id : '';
            return p.title.length > 22 ? p.title.slice(0, 22) + '…' : p.title;
        };
        const onMouseDown = (e) => {
            if (e.target.closest('.collapse-btn') || e.target.closest('.el-button') || e.target.closest('.el-select')) return;
            emit('start-drag', e);
        };
        const toggleFullscreen = () => {
            emit('update:fullscreen', !props.fullscreen);
        };
        return { pdfSrc, currentPaper, shortTitle, onMouseDown, toggleFullscreen, t: window.t || (s => s) };
    }
};
```

  **注意**：组件内的 `t` 与图标（`Link`/`FullScreen`/`ScaleToOriginal`）依赖全局。`window.t` 不存在 —— 需由父级传入 `t` prop 或组件内直接用 `window.appI18n`。简化：**改 props，加 `t: Function`**，由 index.html 挂载处传 `:t="t"`（主 app 已有 `t`），setup 内 `props.t(...)`。修改上面代码中 `t('paper.original')` → `props.t('paper.original')`（模板内用 `t(...)` 时改为 `props.t` 或模板方法 `t`）。为了模板可读，setup 返回 `const t = props.t`。

  用 `app.component` 注册方式（ChatWidget.js 文件尾有同样 pattern，打开它以保持一致）：

```js
app.component('paper-pdf-panel', PaperPdfPanel);
```

- [ ] **Step 2: main.css 追加样式**

```css
/* PDF 阅读面板 */
.pdf-window {
    display: flex;
    flex-direction: column;
    background: var(--bg-primary, #fff);
    border-radius: 12px;
    box-shadow: var(--shadow-lg, 0 12px 32px rgba(0,0,0,.15));
    overflow: hidden;
}
.pdf-window.pdf-window-fullscreen { border-radius: 0; }
.pdf-body {
    flex: 1;
    min-height: 0;
    background: #525659; /* 与浏览器 PDF 底色一致 */
}
.pdf-body iframe { background: #fff; }
.pdf-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%; color: #909399; font-size: 14px;
}
.pdf-window .resize-handle {
    position: absolute; right: 0; bottom: 0; width: 16px; height: 16px;
    cursor: nwse-resize;
}
.pdf-window.fullscreen { position: fixed !important; inset: 0; width: 100vw !important; height: 100vh !important; border-radius: 0; }
.pdf-window.fullscreen .resize-handle { display: none; }
```

  注意 `.chat-window` 已有 `fullscreen` 处理逻辑（`animate-fullscreen`），保持复用 `chat-window` 类是为了继承 header 布局；如果 `.chat-window` 的 fixed 定位自带 transition/animation，则 `.pdf-window` 全屏时靠 ChatWidget 相同的 class 驱动。

- [ ] **Step 3: index.html 注册脚本**

  在 `<script src="js/components/ChatWidget.js"></script>` 后追加：

```html
    <script src="js/components/PaperPdfPanel.js"></script>
```

  并确认 PaperPdfPanel.js 顶部引用全局 `Vue`、`app`（与 ChatWidget.js 相同方式，`app.component(...)` 调用在文件里）。

- [ ] **Step 4: 冒烟验证（单组件探针页）**

  写 `/tmp/pdf_probe.html`（最小 HTML：引入 vue CDN + elementp plus CDN + 组件 js），渲染 `<paper-pdf-panel :show="true" ...>`，用 playwright 打开 → 无 JS 报错、header 按钮渲染。验证后删除。

  更省事替代：直接进入 Task 4 接线后整体验证（组件错误会在 chrome console 报错暴露）。**采用替代**：Step 5 前先整体验证。

- [ ] **Step 5: Commit**

```bash
git add arxiv_pulse/web/static/js/components/PaperPdfPanel.js arxiv_pulse/web/static/css/main.css arxiv_pulse/web/static/index.html
git commit -m "feat: add PaperPdfPanel floating window component"
```

---

### Task 4: ChatWidget「原文」按钮 + 主应用接线（联动拖拽）

**Files:**
- Modify: `arxiv_pulse/web/static/js/components/ChatWidget.js`（header 加按钮；emits 加 `open-pdf`；header 的 props 里已有 `currentLang`，无 `t`? —— 组件内已用 `t('chat.title')`，确认 setup 返回的 `t` 是 props 传入还是全局函数，跟随现有模式）
- Modify: `arxiv_pulse/web/static/index.html`（pdf 状态、openPdfPanel、startDragPdf、bringToFront、Esc、挂载 `<paper-pdf-panel>`、setup return）

**Interfaces:**
- Consumes: Task 3 的 `paper-pdf-panel` 组件、`selectedChatPapers`（index.html setup，`[{arxiv_id, title, ...}]`）、`chatPosition/chatSize/chatExpanded/chatFullscreen/chatAnimating/chatZIndex`、`bringToFront`、`startDragChat/onDrag/stopDrag`、`cartZIndex/detailZIndex/collectionDetailZIndex`
- Produces: `pdfExpanded`、`pdfPosition`（computed）、`pdfSize`、`pdfZIndex`、`pdfFullscreen`、`pdfAnimating`、`pdfOffset`、`currentPdfArxivId`、`openPdfPanel()`、`startDragPdf(e)`、`togglePdfFullscreen()`

- [ ] **Step 1: ChatWidget 加按钮**

  在 chat-header 的 `.chat-title` 与 `.chat-header-actions` 之间（或 buttons 最左）插入：

```html
<el-button text @click.stop="$emit('open-pdf')" :disabled="!('papers' in $props)" >
```

  更具体：`ChatWidget` 的 props 加 `selectedPapers: { type: Array, default: () => [] }`，模板加：

```html
<el-button text @click.stop="$emit('open-pdf')" :disabled="selectedPapers.length === 0" :title="t('paper.noSelection')">
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
        <path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>
    </svg>
</el-button>
```

  emits 数组加 `'open-pdf'`。

- [ ] **Step 2: index.html 状态 + 打开逻辑（在 setup 内 `selectedChatPapers` 定义附近）**

```js
const pdfExpanded = ref(false);
const pdfFullscreen = ref(false);
const pdfAnimating = ref(false);
const pdfZIndex = ref(1500);
const pdfSize = ref({ width: 620, height: 760 });
const pdfOffset = ref({ dx: -632, dy: 0 });
const currentPdfArxivId = ref('');
const pdfPosition = computed(() => ({
    x: Math.max(0, chatPosition.value.x + pdfOffset.value.dx),
    y: Math.max(0, chatPosition.value.y + pdfOffset.value.dy)
}));
const pdfFsZ = computed(() => Math.max(cartZIndex.value, chatZIndex.value, detailZIndex.value, collectionDetailZIndex.value) - 1);

function openPdfPanel() {
    if (!selectedChatPapers.value.length) return;
    const first = selectedChatPapers.value[0];
    const pdfW = Math.min(620, Math.max(360, window.innerWidth * 0.35));
    pdfSize.value.width = pdfW;
    pdfSize.value.height = Math.min(760, window.innerHeight * 0.8);
    const gap = 12;
    let dx = -(pdfW + gap);
    if (chatPosition.value.x + dx < 0) dx = chatSize.value.width + gap; // 左侧放不下则放右侧
    pdfOffset.value = { dx, dy: 0 };
    currentPdfArxivId.value = first.arxiv_id;
    pdfExpanded.value = true;
    bringToFront('pdf');
}
```

- [ ] **Step 3: 联动拖拽（onDrag 扩展）**

  在 `onDrag` 内 `else if (dragTarget === 'chat')` 分支后追加：

```js
} else if (dragTarget === 'pdf') {
    const newX = e.clientX - dragOffset.x;
    const newY = e.clientY - dragOffset.y;
    const deltaX = newX - pdfPosition.value.x;
    const deltaY = newY - pdfPosition.value.y;
    chatPosition.value = { x: chatPosition.value.x + deltaX, y: chatPosition.value.y + deltaY };
}
```

  新函数（照抄 startDragChat 模式）：

```js
function startDragPdf(e) {
    if (e.target.closest('.collapse-btn') || e.target.closest('.el-button') || e.target.closest('.el-select')) return;
    isDragging = true;
    dragTarget = 'pdf';
    dragOffset = { x: e.clientX - pdfPosition.value.x, y: e.clientY - pdfPosition.value.y };
    document.addEventListener('mousemove', onDrag);
    document.addEventListener('mouseup', stopDrag);
}
```

- [ ] **Step 4: 其余接线**

  1. `bringToFront` 加分支：

```js
} else if (panel === 'pdf') {
    pdfZIndex.value = maxZ + 1;
}
```

  2. `maxZ` 计算加入 `pdfZIndex`；`handleEscKey` 的 panels 数组加入 pdf（顺序按 zIndex 排序无特殊处理，`close: () => pdfExpanded.value = false`）。
  3. `toggleChatFullscreen` 旁加：

```js
function togglePdfFullscreen() {
    pdfAnimating.value = true;
    pdfFullscreen.value = !pdfFullscreen.value;
    setTimeout(() => { pdfAnimating.value = false; }, 300);
}
```

  4. 模板挂载（`<chat-widget ...>` 之后）：

```html
<paper-pdf-panel
    :show="pdfExpanded"
    :position="pdfPosition"
    :size="pdfSize"
    :z-index="pdfFullscreen ? pdfFsZ : pdfZIndex"
    :fullscreen="pdfFullscreen"
    :animating="pdfAnimating"
    :current-lang="currentLang"
    :papers="selectedChatPapers"
    :current-arxiv-id="currentPdfArxivId"
    @update:show="pdfExpanded = $event"
    @update:fullscreen="pdfFullscreen = $event"
    @update:current="currentPdfArxivId = $event"
    @bring-to-front="bringToFront('pdf')"
    @start-drag="startDragPdf"
    @open-external="openPdfExternal"
></paper-pdf-panel>
```

  （组件本计划未实现 resize 把手 emit —— 组件模板里有 `.resize-handle` 但无 start-resize 处理；**本计划砍掉 resize**，组件不要 render resize-handle，避免渲染不存在行为的把手。）

  ChatWidget 挂载处加 `:selected-papers="selectedChatPapers"`，并监听 `@open-pdf="openPdfPanel"`。

  5. `openPdfExternal`：

```js
function openPdfExternal() {
    const id = currentPdfArxivId.value;
    if (!id) return;
    window.open(`/api/papers/${id}/pdf`, '_blank');
}
```

  6. setup return 加入：`pdfExpanded, pdfPosition, pdfSize, pdfZIndex, pdfFullscreen, pdfAnimating, currentPdfArxivId, openPdfPanel, startDragPdf, togglePdfFullscreen, openPdfExternal`。

- [ ] **Step 5: 移除组件模板中未实现的 resize 把手**（若 Step 1 已含，删掉 `<div class="resize-handle"></div>` 并确认无 start-resize 引用）

- [ ] **Step 6: 整体验证（Playwright，临时脚本，验证后删）**

  临时实例起依赖 Task 1 端点，直接对着 8000 用户实例只做前端验证会写缓存 —— 采用临时实例 8103 + 种数据（复用 Task 1 Step 3 方法），验证：

  1. 打开 `http://127.0.0.1:8103/` → 点论文卡「分析」→ chat 浮窗出现
  2. 点 header「原文」→ pdf 面板出现在 chat 左侧，`iframe` 存在且 src 含 `/api/papers/`
  3. 拖 chat（mousedown 在 header + mousemove）→ `pdfPosition` 同步变化（page.evaluate 读取 `__vue_app__` 或 DOM style 断言）
  4. 拖 pdf → chat 位置同步
  5. 点最大化 → `.pdf-window.fullscreen` 存在；点还原 → 回到位置
  6. 无 console error

- [ ] **Step 7: Commit**

```bash
git add arxiv_pulse/web/static/js/components/ChatWidget.js arxiv_pulse/web/static/index.html
git commit -m "feat: link original-PDF panel to chat window with linked dragging"
```

---

### Task 5: 回归 + 收尾

**Files:** 无新增（只验证/清理）

- [ ] **Step 1: 后端全量回归**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8103/api/papers/2608.26820/pdf   # 200
curl -s http://127.0.0.1:8103/api/recent -o /dev/null -w "%{http_code}\n"                    # 200（未回归）
```

- [ ] **Step 2: 前端人工检查清单**（对 8000 用户实例：静态文件自动生效，Ctrl+Shift+R 强刷）

- [ ] 首页「搜索」按钮、论文集弹窗「搜索」按钮还在（Task 之前功能）
- [ ] chat 正常收发（未受影响）
- [ ] 「原文」按钮无选中论文时置灰

- [ ] **Step 3: 清理临时文件**

```bash
rm -f /tmp/pdf_probe.html /tmp/_seed.py
rm -rf tests/tmp_verify_data
```

- [ ] **Step 4: Commit（如收尾有改动）**

```bash
git status --short
# 只 add 本计划文件；若无改动跳过
```

---

## Self-Review 记录

- **Spec coverage**：
  - 后端端点/缓存/302 → Task 1 ✓
  - 原文按钮/贴合打开/多篇切换/最大化/新标签兜底 → Task 3+4 ✓
  - 联动拖拽（拖任一个两个走）→ Task 4 Step 3 ✓
  - 全屏 zIndex 低于助手 → Task 4 挂载 `z-index=fullscreen ? pdfFsZ : pdfZIndex` ✓
  - Esc/关闭/重开贴合 → Task 4 Step 4 ✓（重开逻辑在 openPdfPanel 每次重算 offset）
  - i18n → Task 2 ✓
  - 样式 → Task 3 ✓
- **不一致修正**：组件模板里最初写了 resize-handle 与 start-resize，计划砍掉功能后明确在 Task 4 Step 5 移除把手；组件 emits 相应去掉 `start-resize`（Task 3 Step 1 代码里已带 —— 执行时以 Step 5 为准，即组件代码中不渲染把手、emits 不含 start-resize）。
- **类型一致性**：`pdfPosition` 为 computed（非 ref，只读）—— openPdfExternal/startDragPdf 读 `.value.x` ✓；`pdfOffset` ref 含 dx/dy ✓；`pdfFsZ` computed ✓。
