const PaperPdfPanelTemplate = `
    <transition name="panel">
        <div v-if="show"
             class="chat-window pdf-window"
             :class="{ fullscreen: fullscreen, 'animate-fullscreen': animating }"
             :style="fullscreen ? { zIndex: zIndex } : { position: 'fixed', left: position.x + 'px', top: position.y + 'px', width: size.width + 'px', height: size.height + 'px', zIndex: zIndex }"
             @mousedown="onMouseDown"
             @click="$emit('bring-to-front')">
            <div class="chat-header pdf-header">
                <span class="chat-title">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                        <path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM6 20V4h5v6h5v10H6z"/>
                    </svg>
                    {{ t('paper.original') }}
                </span>
                <div class="chat-header-actions pdf-header-actions">
                    <el-select v-model="currentPaper" size="small" class="pdf-paper-select" :placeholder="t('paper.original')">
                        <el-option v-for="p in papers" :key="p.arxiv_id" :label="shortTitle(p)" :value="p.arxiv_id"></el-option>
                    </el-select>
                    <el-button text @click.stop="$emit('open-external')" :title="t('paper.openExternal')">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                            <path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/>
                        </svg>
                    </el-button>
                    <el-button text @click.stop="toggleFullscreen" :title="fullscreen ? (currentLang === 'zh' ? '还原' : 'Restore') : (currentLang === 'zh' ? '全屏' : 'Fullscreen')">
                        <svg v-if="fullscreen" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                            <path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>
                        </svg>
                        <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                            <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>
                        </svg>
                    </el-button>
                    <div class="collapse-btn" @click.stop="$emit('update:show', false)" :title="currentLang === 'zh' ? '关闭' : 'Close'">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                        </svg>
                    </div>
                </div>
            </div>
            <div class="pdf-body">
                <iframe v-if="currentArxivId" :key="currentArxivId" :src="pdfSrc" title="PDF" @load="pdfLoading = false"></iframe>
                <div v-if="pdfLoading && currentArxivId" class="pdf-loading">
                    <el-icon class="is-loading"><Loading /></el-icon>
                    <span>{{ t('pdf.loading') }}</span>
                </div>
                <div v-else-if="!currentArxivId" class="pdf-empty">{{ t('paper.noSelection') }}</div>
            </div>
        </div>
    </transition>
`;

const PaperPdfPanelSetup = (props, { emit }) => {
    const pdfLoading = ref(true);
    let loadTimer = null;
    const resetLoading = () => {
        pdfLoading.value = true;
        clearTimeout(loadTimer);
        loadTimer = setTimeout(() => { pdfLoading.value = false; }, 8000);
    };
    resetLoading();
    watch(() => props.currentArxivId, resetLoading);
    onBeforeUnmount(() => clearTimeout(loadTimer));
    const pdfSrc = computed(() => {
        const file = `/api/papers/${props.currentArxivId}/pdf`;
        return `/vendor/pdfjs/web/viewer.html?file=${encodeURIComponent(file)}`;
    });
    const currentPaper = computed({
        get: () => props.currentArxivId,
        set: (v) => emit('update:current', v)
    });
    const shortTitle = (p) => {
        if (!p) return '';
        if (p.title) return p.title.length > 22 ? p.title.slice(0, 22) + '…' : p.title;
        return p.arxiv_id;
    };
    const onMouseDown = (e) => {
        if (e.target.closest('.collapse-btn') || e.target.closest('.el-button') || e.target.closest('.el-select')) return;
        emit('start-drag', e);
    };
    const toggleFullscreen = () => {
        emit('update:fullscreen', !props.fullscreen);
    };
    const t = props.t;
    return { pdfSrc, currentPaper, shortTitle, onMouseDown, toggleFullscreen, t, pdfLoading };
};
