const PaperCardTemplate = `
<div class="paper-card" :data-arxiv-id="paper.arxiv_id" ref="cardRef">
    <div class="paper-header">
        <div class="paper-title" @click="openArxiv(paper.arxiv_id)" v-html="renderLatex(paper.title)"></div>
        <span v-if="index !== undefined" class="paper-index">{{ index + 1 }}</span>
    </div>
    <div v-if="paper.title_translation" class="paper-title-cn" v-html="renderLatex(paper.title_translation)"></div>
    <div v-else-if="!paper.ai_available" class="paper-title-cn" style="color: var(--text-muted); font-style: italic;">
        {{ isZh ? '未配置 AI API Key，无法翻译' : 'AI API Key not configured' }}
    </div>
    <div class="paper-meta">
        <span class="paper-meta-item">
            <el-icon><Calendar /></el-icon>
            {{ formatDate(paper.published) }}
        </span>
        <span class="paper-meta-item">
            <el-icon><User /></el-icon>
            {{ paper.authors?.slice(0, 2).map(a => a.name).join(', ') }}{{ paper.authors?.length > 2 ? (isZh ? ' 等' : ' et al.') : '' }}
        </span>
        <span v-if="paper.search_relevance_score" class="paper-meta-item relevance-badge" :title="isZh ? '搜索相关性评分' : 'Search relevance score'">
            🎯 {{ paper.search_relevance_score }}
        </span>
        <span v-if="paper.is_oa === 'yes'" class="paper-meta-item oa-badge" :title="'Open Access'">{{ isZh ? '开放' : 'OA' }}</span>
        <span v-else-if="paper.is_oa === 'no' && paper.has_manual_pdf" class="paper-meta-item oa-badge" :title="isZh ? '用户已上传 PDF 获取全文' : 'PDF uploaded by user'">{{ isZh ? '开放' : 'OA' }}</span>
        <span v-else-if="paper.is_oa === 'no'" class="paper-meta-item oa-badge no-oa" :title="isZh ? '非开放获取' : 'Not Open Access'">{{ isZh ? '闭源' : 'Closed' }}</span>
    </div>
    <div class="paper-category" v-if="categoryExplanation">{{ categoryExplanation }}</div>

    <div class="abstract-section" v-if="paper.abstract || (paper.key_findings && paper.key_findings.length)">
        <p v-if="paper.abstract" class="abstract-text" :class="{ 'abstract-collapsed': !expanded }" v-html="renderLatex(paper.abstract)"></p>
        <div v-else class="abstract-text abstract-collapsed" style="color: var(--text-secondary); font-size: 13px;">
            <div v-for="(f, i) in paper.key_findings.slice(0, 3)" :key="i" style="margin: 3px 0;">• {{ f }}</div>
        </div>
    </div>
    
    <template v-if="expanded">
        <div v-if="generating" class="ai-generating-hint">
            <span class="ai-generating-spinner"></span>
            {{ paper._summaryStage || (isZh ? '正在处理...' : 'Processing...') }}
        </div>
        <div v-if="paper.abstract_translation" class="translation-section">
            <h4>{{ t('paper.chineseTranslation') }}</h4>
            <p v-html="renderLatex(paper.abstract_translation)"></p>
        </div>
        <div v-else-if="!paper.ai_available" class="translation-section" style="color: var(--text-muted); font-style: italic;">
            <h4>{{ t('paper.chineseTranslation') }}</h4>
            <p>{{ isZh ? '未配置 AI API Key，无法翻译。请在设置中配置。' : 'AI API Key not configured.' }}</p>
        </div>
        
        <div v-if="paper.keywords && paper.keywords.length" class="paper-keywords">
            <h4>{{ t('paper.keywords') }}</h4>
            <div class="keywords-list">
                <el-tag v-for="kw in paper.keywords" :key="kw" size="small" type="info">{{ kw }}</el-tag>
            </div>
        </div>
        
        <div v-if="paper.figure_url" class="paper-figure">
            <img :src="paper.figure_url" @click="openImage(paper.figure_url)" @error="onFigureError" />
        </div>
        
        <div v-if="paper.methodology" class="methodology-section">
            <h4>{{ t('paper.methodology') }}</h4>
            <p v-html="renderLatex(paper.methodology)"></p>
        </div>
        
        <div v-if="paper.key_findings && paper.key_findings.length" class="key-findings">
            <h4>{{ t('paper.keyFindings') }}</h4>
            <ul>
                <li v-for="(finding, i) in paper.key_findings" :key="i" v-html="renderLatex(finding)"></li>
            </ul>
        </div>
        
        <div v-if="(!paper.key_findings || !paper.key_findings.length) && !paper.methodology && (!paper.keywords || !paper.keywords.length) && !paper.ai_available" style="color: var(--text-muted); font-style: italic; padding: 10px 0;">
            <p>{{ isZh ? '未配置 AI API Key，无法生成总结。请在设置中配置。' : 'AI API Key not configured.' }}</p>
        </div>

        <div v-if="showPdfUploadOffer" class="pdf-manual-offer">
            <el-button size="small" type="warning" plain @click="uploadPdfForSummary" :loading="uploadingPdf">
                <el-icon><Upload /></el-icon> {{ t('paper.uploadPdfEnrich') }}
            </el-button>
            <span class="pdf-manual-offer-hint">{{ isZh ? '未找到摘要，无法自动生成总结。可手动下载 PDF 上传，获取完整 AI 总结。' : 'No abstract found. Upload the PDF for a full AI summary.' }}</span>
        </div>
    </template>
    
    <div class="paper-actions">
        <el-button size="small" text type="primary" @click="openArxiv(paper.arxiv_id)">
            <el-icon><Promotion /></el-icon> DOI
        </el-button>
        <el-button size="small" text type="primary" @click="downloadCard">
            <el-icon><Picture /></el-icon> {{ t('paper.card') }}
        </el-button>
        <el-button v-if="!inCart" size="small" text type="warning" @click="$emit('add-to-cart', paper)">
            <el-icon><Star /></el-icon> {{ t('paper.bookmark') }}
        </el-button>
        <el-button v-else size="small" type="warning" plain @click="$emit('remove-from-cart', paper.arxiv_id)">
            <el-icon><StarFilled /></el-icon> {{ t('paper.bookmarked') }}
        </el-button>
        <el-button size="small" text type="primary" @click="analyzePaper">
            <el-icon><ChatDotRound /></el-icon> {{ t('paper.analyze') }}
        </el-button>
        <el-button size="small" text type="primary" @click="$emit('add-to-collection', paper)">
            <el-icon><Folder /></el-icon> {{ t('paper.addToCollection') }}
        </el-button>
        <el-button v-if="inCollection" size="small" text type="danger" @click="$emit('remove-from-collection', paper.id)">
            <el-icon><Delete /></el-icon> {{ t('paper.removeFromCollection') }}
        </el-button>
        <el-button size="small" text @click="toggleExpand">
            {{ expanded ? t('paper.collapse') : t('paper.expandDetail') }}
        </el-button>
    </div>
</div>
`;

const PaperCardSetup = (props, { emit }) => {
    const expanded = ref(props.startExpanded || false);
    const cardRef = ref(null);
    const generating = ref(false);

    const t = props.t || ((key) => key);
    const isZh = computed(() => props.currentLang === 'zh');

    // AI 总结完成后停止生成中动效（成功 summarized / 失败 _summarizing=false 任一都会触发）
    watch(() => props.paper.summarized, (v) => {
        if (v) generating.value = false;
    });
    watch(() => props.paper._summarizing, (v) => {
        if (v === false) generating.value = false;
    });

    // 已总结但只有基础总结（无 findings/methodology）的论文，展开时自动升级为完整总结
    const needsSummaryUpgrade = computed(() => {
        const p = props.paper;
        if (!p.summarized || p.source === 'arxiv') return false;
        return !p.key_findings || !p.key_findings.length || !p.methodology;
    });

    const toggleExpand = () => {
        const wasExpanded = expanded.value;
        expanded.value = !expanded.value;

        // 展开时按需触发 AI 总结与首图生成（未总结或基础总结的论文都会触发升级）
        if (!wasExpanded && (!props.paper.summarized || needsSummaryUpgrade.value) && !generating.value) {
            generating.value = true;
            emit('request-summary', props.paper);
            // 兜底：无论后端起什么原因，120s 后强制停止生成中动效，避免永久转圈
            setTimeout(() => {
                generating.value = false;
            }, 120000);
        }

        if (wasExpanded && cardRef.value) {
            setTimeout(() => {
                cardRef.value.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 50);
        }
    };

    // 仅对非 arXiv 且无有效总结的论文显示「手动上传 PDF 补充总结」
    const showPdfUploadOffer = computed(() => {
        const p = props.paper;
        if (p.source === 'arxiv') return false;
        if (!p.summarized) return !!p._summaryFailed;  // 总结失败（无摘要）时也显示上传建议
        if (p._summaryNoAbstract) return true;          // 降级基础总结（无摘要）时提示上传
        const noFindings = !p.key_findings || !p.key_findings.length;
        const noMethodology = !p.methodology;
        return noFindings && noMethodology;
    });

    const uploadingPdf = ref(false);
    const uploadPdfForSummary = () => {
        if (uploadingPdf.value) return;
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.pdf';
        fileInput.onchange = async () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) return;
            uploadingPdf.value = true;
            const p = props.paper;
            try {
                const form = new FormData();
                form.append('pid', p.arxiv_id);
                form.append('file', file);
                const res = await fetch('/api/chat/pdf/upload', { method: 'POST', body: form });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || 'upload failed');
                // 上传成功：触发重新总结（会命中刚存的全文缓存）
                generating.value = true;
                try {
                    const sumRes = await fetch(`/api/papers/${p.id}/summarize`, { method: 'POST' });
                    if (sumRes.ok) {
                        const sumData = await sumRes.json();
                        if (sumData.paper) Object.assign(p, sumData.paper);
                    }
                } finally {
                    generating.value = false;
                }
                const msg = isZh.value
                    ? 'PDF 已上传并生成完整总结'
                    : 'PDF uploaded, full summary generated';
                ElementPlus.ElMessage.success(msg);
            } catch (e) {
                console.error('上传 PDF 失败:', e);
                ElementPlus.ElMessage.error(isZh.value ? '上传失败: ' + e.message : 'Upload failed: ' + e.message);
            } finally {
                uploadingPdf.value = false;
            }
        };
        fileInput.click();
    };

    const onFigureError = (e) => {
        if (e && e.target) e.target.style.display = 'none';
    };

    const formatDate = (dateStr) => {
        if (!dateStr) return '';
        return new Date(dateStr).toLocaleDateString('zh-CN');
    };
    
    const formatSummary = (text) => {
        if (!text) return '';
        return text.replace(/\n/g, '<br>');
    };
    
    const escapeHtml = (text) => {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    };
    
    const renderLatex = (text) => {
        if (!text) return '';
        
        if (typeof katex === 'undefined') {
            return escapeHtml(text);
        }
        
        const parts = [];
        let lastIndex = 0;
        
        const patterns = [
            { regex: /\$\$([^$]+)\$\$/g, displayMode: true },
            { regex: /\\\[([^\\\]]+)\\\]/g, displayMode: true },
            { regex: /\\\(([^)]+)\\\)/g, displayMode: false },
            { regex: /\$([^$]+)\$/g, displayMode: false },
        ];
        
        const allMatches = [];
        
        for (const { regex, displayMode } of patterns) {
            let match;
            const re = new RegExp(regex.source, regex.flags);
            while ((match = re.exec(text)) !== null) {
                allMatches.push({
                    start: match.index,
                    end: match.index + match[0].length,
                    latex: match[1],
                    displayMode,
                    fullMatch: match[0],
                });
            }
        }
        
        allMatches.sort((a, b) => a.start - b.start);
        
        const filteredMatches = [];
        for (const m of allMatches) {
            if (filteredMatches.length === 0 || m.start >= filteredMatches[filteredMatches.length - 1].end) {
                filteredMatches.push(m);
            }
        }
        
        for (const m of filteredMatches) {
            if (m.start > lastIndex) {
                parts.push(escapeHtml(text.slice(lastIndex, m.start)));
            }
            try {
                const html = katex.renderToString(m.latex, {
                    displayMode: m.displayMode,
                    throwOnError: false,
                    trust: true,
                });
                parts.push(html);
            } catch (e) {
                parts.push(escapeHtml(m.fullMatch));
            }
            lastIndex = m.end;
        }
        
        if (lastIndex < text.length) {
            parts.push(escapeHtml(text.slice(lastIndex)));
        }
        
        return parts.join('');
    };
    
    const openArxiv = (arxivId) => {
        const paper = props.paper || {};
        if (paper.source === 'doi') {
            window.open(paper.pdf_url || `https://doi.org/${arxivId}`, '_blank');
            return;
        }
        window.open(`https://arxiv.org/abs/${arxivId}`, '_blank');
    };

    const openImage = (url) => {
        window.open(url, '_blank');
    };
    
    const downloadCard = async () => {
        const scale = 2;
        const width = 700 * scale;
        const padding = 32 * scale;
        
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        
        const stripMarkdown = (text) => {
            if (!text) return '';
            return text
                .replace(/\*\*([^*]+)\*\*/g, '$1')
                .replace(/\*([^*]+)\*/g, '$1')
                .replace(/__([^_]+)__/g, '$1')
                .replace(/_([^_]+)_/g, '$1')
                .replace(/`([^`]+)`/g, '$1')
                .replace(/~~([^~]+)~~/g, '$1');
        };
        
        const wrapText = (text, maxWidth, fontSize, fontFamily = 'sans-serif', fontWeight = 'normal') => {
            if (!text) return [];
            const cleanText = stripMarkdown(text);
            ctx.font = `${fontWeight} ${fontSize * scale}px ${fontFamily}`;
            const chars = cleanText.split('');
            const result = [];
            let current = '';
            for (const char of chars) {
                const test = current + char;
                if (ctx.measureText(test).width > maxWidth && current) {
                    result.push(current);
                    current = char;
                } else {
                    current = test;
                }
            }
            if (current) result.push(current);
            return result;
        };
        
        let y = padding;
        const elements = [];
        
        const titleLines = wrapText(props.paper.title, width - padding * 2, 20, 'Georgia, "Noto Serif SC", serif', 'bold');
        titleLines.forEach(line => {
            elements.push({ type: 'text', text: line, font: `bold ${20 * scale}px Georgia, "Noto Serif SC", serif`, color: '#1e3a5f', y: y });
            y += 32 * scale;
        });
        
        if (props.paper.title_translation) {
            const transLines = wrapText(props.paper.title_translation, width - padding * 2, 16);
            transLines.forEach(line => {
                elements.push({ type: 'text', text: line, font: `italic ${16 * scale}px sans-serif`, color: '#5a6c7d', y: y });
                y += 26 * scale;
            });
            y += 8 * scale;
        }
        
        const pubDate = props.paper.published ? new Date(props.paper.published).toLocaleDateString('zh-CN') : 'N/A';
        const authors = props.paper.authors?.slice(0, 4).map(a => a.name).join(', ') || '';
        elements.push({ type: 'text', text: `${pubDate}  |  ${authors}${props.paper.authors?.length > 4 ? ' 等' : ''}`, font: `${13 * scale}px sans-serif`, color: '#909399', y: y });
        y += 36 * scale;
        
        elements.push({ type: 'divider', y: y });
        y += 20 * scale;
        
        elements.push({ type: 'section-title', text: '摘要 (Abstract)', y: y });
        y += 28 * scale;
        
        const abstractLines = wrapText(props.paper.abstract || '', width - padding * 2, 14);
        abstractLines.forEach(line => {
            elements.push({ type: 'text', text: line, font: `${14 * scale}px sans-serif`, color: '#444', y: y });
            y += 22 * scale;
        });
        y += 16 * scale;
        
        if (props.paper.abstract_translation) {
            elements.push({ type: 'section-title', text: t('paper.chineseTranslation'), y: y });
            y += 28 * scale;
            const transAbstractLines = wrapText(props.paper.abstract_translation, width - padding * 2, 14);
            transAbstractLines.forEach(line => {
                elements.push({ type: 'text', text: line, font: `${14 * scale}px sans-serif`, color: '#555', y: y });
                y += 22 * scale;
            });
            y += 16 * scale;
        }
        
        if (props.paper.keywords?.length) {
            elements.push({ type: 'section-title', text: '关键词', y: y });
            y += 28 * scale;
            const keywordsText = props.paper.keywords.join('  •  ');
            const keywordLines = wrapText(keywordsText, width - padding * 2, 13);
            keywordLines.forEach(line => {
                elements.push({ type: 'text', text: line, font: `${13 * scale}px sans-serif`, color: '#c9a227', y: y });
                y += 20 * scale;
            });
            y += 16 * scale;
        }
        
        if (props.paper.figure_url) {
            try {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                await new Promise((resolve, reject) => {
                    img.onload = resolve;
                    img.onerror = reject;
                    img.src = props.paper.figure_url;
                });
                const maxImgWidth = width - padding * 2;
                const imgScale = Math.min(1, maxImgWidth / img.width);
                const imgDrawWidth = img.width * imgScale;
                const imgDrawHeight = img.height * imgScale;
                elements.push({ type: 'image', img, y, width: imgDrawWidth, height: imgDrawHeight });
                y += imgDrawHeight + 20 * scale;
            } catch (e) {}
        }
        
        if (props.paper.methodology) {
            elements.push({ type: 'section-title', text: '研究方法', y: y });
            y += 28 * scale;
            const methodLines = wrapText(props.paper.methodology, width - padding * 2, 14);
            methodLines.forEach(line => {
                elements.push({ type: 'text', text: line, font: `${14 * scale}px sans-serif`, color: '#409EFF', y: y });
                y += 22 * scale;
            });
            y += 16 * scale;
        }
        
        if (props.paper.key_findings?.length) {
            elements.push({ type: 'section-title', text: '关键发现', y: y });
            y += 28 * scale;
            props.paper.key_findings.forEach(finding => {
                const findingLines = wrapText(`• ${finding}`, width - padding * 2 - 20 * scale, 14);
                findingLines.forEach(line => {
                    elements.push({ type: 'text', text: line, font: `${14 * scale}px sans-serif`, color: '#5a6c7d', y: y });
                    y += 22 * scale;
                });
            });
            y += 12 * scale;
        }
        
        y += 16 * scale;
        elements.push({ type: 'divider', y: y });
        y += 20 * scale;
        
        elements.push({ type: 'text', text: `${props.paper.source === 'doi' ? 'DOI' : 'arXiv'}: ${props.paper.arxiv_id}`, font: `${12 * scale}px sans-serif`, color: '#909399', y: y });
        y += 24 * scale;
        elements.push({ type: 'text', text: 'PaperFlow', font: `bold ${13 * scale}px Georgia, serif`, color: '#c9a227', y: y });
        y += 14 * scale;
        elements.push({ type: 'text', text: 'github.com/kYangLi/arXiv-Pulse', font: `${10 * scale}px sans-serif`, color: '#b0b0b0', y: y });
        
        const height = y + padding;
        canvas.width = width;
        canvas.height = height;
        
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, width, height);
        
        ctx.fillStyle = '#1e3a5f';
        ctx.fillRect(0, 0, 6 * scale, height);
        
        ctx.fillStyle = '#c9a227';
        ctx.fillRect(0, height - 4 * scale, width, 4 * scale);
        
        for (const el of elements) {
            if (el.type === 'text') {
                ctx.font = el.font;
                ctx.fillStyle = el.color;
                ctx.fillText(el.text, padding, el.y);
            } else if (el.type === 'section-title') {
                ctx.font = `bold ${15 * scale}px sans-serif`;
                ctx.fillStyle = '#1e3a5f';
                ctx.fillText(el.text, padding, el.y);
                ctx.fillStyle = '#c9a227';
                ctx.fillRect(padding, el.y + 6 * scale, 40 * scale, 2 * scale);
            } else if (el.type === 'divider') {
                ctx.strokeStyle = '#e8e6e1';
                ctx.lineWidth = 1 * scale;
                ctx.beginPath();
                ctx.moveTo(padding, el.y);
                ctx.lineTo(width - padding, el.y);
                ctx.stroke();
            } else if (el.type === 'image') {
                ctx.drawImage(el.img, padding, el.y, el.width, el.height);
            }
        }
        
        const link = document.createElement('a');
        link.download = `paper_${props.paper.arxiv_id}.png`;
        link.href = canvas.toDataURL('image/png', 1.0);
        link.click();
        
        ElementPlus.ElMessage.success('已导出卡片图片');
    };
    
    const analyzePaper = () => {
        window.dispatchEvent(new CustomEvent('analyze-paper', { detail: props.paper }));
    };
    
    const categoryExplanation = computed(() => {
        if (isZh.value) {
            return props.paper.category_explanation_zh || props.paper.category_explanation || '';
        }
        return props.paper.category_explanation_en || props.paper.category_explanation || '';
    });
    
    return { expanded, generating, cardRef, toggleExpand, formatDate, formatSummary, renderLatex, openArxiv, openImage, downloadCard, analyzePaper, onFigureError, t, isZh, categoryExplanation, showPdfUploadOffer, uploadPdfForSummary, uploadingPdf };
};
