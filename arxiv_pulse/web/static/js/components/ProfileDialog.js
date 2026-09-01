const ProfileDialogTemplate = `
    <el-dialog :model-value="show" @update:model-value="v => $emit('update:show', v)" width="660px" append-to-body
               :title="editing ? t('settings.profilesEdit') : t('settings.profilesCreate')">
        <el-form label-width="100px">
            <el-form-item :label="t('settings.profileName')">
                <el-input v-model="name" :placeholder="t('settings.profileNamePh')"></el-input>
            </el-form-item>
            <el-form-item :label="t('settings.profileDesc')">
                <el-input v-model="description" type="textarea" :rows="3" :placeholder="t('settings.profileDescPh')"></el-input>
            </el-form-item>
            <el-form-item>
                <el-button size="small" @click="doGenerate" :loading="generating">{{ t('settings.profileGenerate') }}</el-button>
                <span style="margin-left: 10px; font-size: 12px; color: var(--text-muted);">{{ t('settings.profileGenerateHint') }}</span>
            </el-form-item>
            <el-form-item v-if="plan" :label="t('settings.profilePlan')">
                <div style="width: 100%;">
                    <div class="profile-fold-head" @click="planOpen = !planOpen">
                        <span>
                            {{ currentLang === 'zh' ? ('检索规则（共 ' + ((plan.arxiv_queries || []).length + (plan.s2_query ? 1 : 0)) + ' 条）') : ('Rules (' + ((plan.arxiv_queries || []).length + (plan.s2_query ? 1 : 0)) + ')') }}
                        </span>
                        <span class="fold-arrow">{{ planOpen ? '▾' : '▸' }}</span>
                    </div>
                    <div v-show="planOpen" style="padding-top: 8px;">
                        <div v-for="(item, i) in plan.arxiv_queries" :key="i" style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                            <el-tag size="small" type="info" style="flex-shrink: 0; width: 58px; text-align: center; margin: 0;">arXiv</el-tag>
                            <el-input size="small" v-model="plan.arxiv_queries[i]"></el-input>
                        </div>
                        <div v-if="plan.s2_query || (plan.arxiv_queries || []).length" style="display: flex; align-items: center; gap: 6px; margin-top: 4px;">
                            <el-tag size="small" type="warning" style="flex-shrink: 0; width: 58px; text-align: center; margin: 0;">S2</el-tag>
                            <el-input size="small" v-model="plan.s2_query" :placeholder="t('settings.profileS2Ph')"></el-input>
                        </div>
                        <p style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">
                            {{ currentLang === 'zh' ? '每行一个检索规则：arXiv 行按关键词检索 arXiv；S2 行为语义检索关键词。' : 'One rule per line: arXiv lines query arXiv; S2 line is a semantic query.' }}
                        </p>
                    </div>
                </div>
            </el-form-item>
            <el-form-item v-if="plan" :label="t('settings.profileKeywords')">
                <div style="width: 100%;">
                    <div class="profile-fold-head" @click="kwOpen = !kwOpen">
                        <span>
                            {{ currentLang === 'zh' ? '关键词过滤（' + ((plan.keywords || []).length) + ' 个）' : 'Keywords (' + ((plan.keywords || []).length) + ')' }}
                        </span>
                        <span class="fold-arrow">{{ kwOpen ? '▾' : '▸' }}</span>
                    </div>
                    <div v-show="kwOpen" style="padding-top: 8px;">
                        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px;">
                            <el-tag v-for="(kw, i) in visibleKeywords" :key="i" closable @close="removeKeyword(i)">{{ kw }}</el-tag>
                            <el-tag v-if="!plan.keywords || plan.keywords.length === 0" type="info" style="border-style: dashed;">{{ t('settings.profileJournalNone') }}</el-tag>
                            <el-tag v-else-if="!showAllKeywords && plan.keywords.length > 4" size="small" type="info" style="cursor: pointer; border-style: dashed;" @click="showAllKeywords = true">
                                {{ currentLang === 'zh' ? ('查看全部 ' + plan.keywords.length) : ('Show all ' + plan.keywords.length) }}
                            </el-tag>
                            <el-tag v-else-if="showAllKeywords && plan.keywords.length > 4" size="small" type="info" style="cursor: pointer; border-style: dashed;" @click="showAllKeywords = false">
                                {{ currentLang === 'zh' ? '收起' : 'Collapse' }}
                            </el-tag>
                        </div>
                        <el-input size="small" v-model="keywordInput" :placeholder="t('settings.profileKeywordsPh')" @keyup.enter="addKeyword"></el-input>
                    </div>
                </div>
            </el-form-item>
            <el-form-item :label="t('settings.profileJournals')">
                <div style="width: 100%;">
                    <el-select filterable remote :remote-method="doSearchJournals" :loading="catalogLoading"
                               v-model="pickedIssn" :placeholder="t('settings.profileJournalPickPh')"
                               style="width: 100%;" @change="addFromCatalog">
                        <el-option v-for="j in catalogItems" :key="j.issn" :value="j.issn" :label="j.title">
                            <div style="display: flex; justify-content: space-between; gap: 10px;">
                                <span>{{ j.title }}</span>
                                <span style="flex-shrink: 0; font-size: 11px; color: var(--text-muted);">{{ (j.quartile ? j.quartile + ' · ' : '') + (j.publisher || '') }}</span>
                            </div>
                        </el-option>
                    </el-select>
                    <div v-if="journalSyncing" style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                        {{ t('settings.profileJournalSyncing') }} ({{ journalCatalogCount }})
                    </div>
                    <div style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px;">
                        <el-tag v-for="(j, i) in journalTemplates" :key="j.issn" closable @close="removeJournal(i)">{{ j.name }}</el-tag>
                        <el-tag v-if="journalTemplates.length === 0" type="info" style="border-style: dashed;">{{ t('settings.profileJournalNone') }}</el-tag>
                    </div>
                </div>
            </el-form-item>
            <el-form-item :label="t('settings.profileSources')">
                <el-checkbox v-model="sources.arxiv">arXiv</el-checkbox>
                <el-checkbox v-model="sources.crossref">Crossref/OpenAlex</el-checkbox>
                <el-checkbox v-model="sources.s2">Semantic Scholar (S2)</el-checkbox>
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="$emit('update:show', false)">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" @click="save" :loading="saving">{{ t('common.save') }}</el-button>
        </template>
    </el-dialog>
`;

const ProfileDialogSetup = (props, { emit }) => {
    const profileStore = useProfileStore();
    const configStore = useConfigStore();
    const name = ref('');
    const description = ref('');
    const plan = ref(null);
    const generating = ref(false);
    const saving = ref(false);
    const sources = reactive({ arxiv: true, crossref: true, s2: true });
    const journalTemplates = ref([
        { key: 'tgrs', name: 'IEEE TGRS', issn: '1558-0644', enabled: true },
        { key: 'science', name: 'Science', issn: '0036-8075', enabled: true }
    ]);

    const catalogItems = ref([]);
    const catalogLoading = ref(false);
    const journalSyncing = ref(false);
    const journalCatalogCount = ref(0);
    const pickedIssn = ref('');
    let catalogTimer = null;

    const keywordInput = ref('');
    const showAllKeywords = ref(false);
    const planOpen = ref(false);
    const kwOpen = ref(false);

    watch(() => props.show, async (v) => {
        if (!v) return;
        showAllKeywords.value = false;
        planOpen.value = false;
        kwOpen.value = false;
        const editing = props.editing === undefined ? null : props.editing;
        if (!editing) {
            name.value = '';
            description.value = '';
            plan.value = null;
            sources.arxiv = sources.crossref = sources.s2 = true;
            journalTemplates.value = [
                { key: 'tgrs', name: 'IEEE TGRS', issn: '1558-0644', enabled: true },
                { key: 'science', name: 'Science', issn: '0036-8075', enabled: true }
            ];
        } else {
            let p = profileStore.profiles.find(x => x.id === editing);
            if (!p) {
                // 档案列表尚未加载完时的竞态兜底：主动拉取一次
                try {
                    await profileStore.fetchProfiles();
                } catch (_e) {}
                p = profileStore.profiles.find(x => x.id === editing);
            }
            if (!p) return;
            name.value = p.name;
            description.value = p.description || '';
            plan.value = p.retrieval_plan || null;
            sources.arxiv = p.sources.arxiv !== false;
            sources.crossref = p.sources.crossref !== false;
            sources.s2 = p.sources.s2 !== false;
            journalTemplates.value = (p.journals && p.journals.length ? p.journals : journalTemplates.value)
                .filter(j => j.enabled !== false)
                .map(j => ({ key: j.key, name: j.name, issn: j.issn, enabled: true }));
        }
        doSearchJournals('');
    }, { immediate: true });

    onUnmounted(() => {
        if (catalogTimer) { clearInterval(catalogTimer); catalogTimer = null; }
    });

    async function doSearchJournals(q = '') {
        catalogLoading.value = true;
        try {
            const data = await profileStore.searchJournalCatalog(q);
            catalogItems.value = data.items || [];
            journalSyncing.value = !!data.syncing;
            journalCatalogCount.value = data.count || 0;
            if (data.syncing && !catalogTimer) {
                catalogTimer = setInterval(pollCatalogStatus, 1500);
            }
        } catch (e) {
            console.error('期刊目录搜索失败:', e);
        } finally {
            catalogLoading.value = false;
        }
    }

    async function pollCatalogStatus() {
        const st = await profileStore.journalCatalogStatus();
        journalSyncing.value = !!st.syncing;
        journalCatalogCount.value = st.count || 0;
        if (!st.syncing && catalogTimer) {
            clearInterval(catalogTimer);
            catalogTimer = null;
            doSearchJournals('');
        }
    }

    function addFromCatalog(issn) {
        const j = catalogItems.value.find(x => x.issn === issn);
        if (j) {
            if (journalTemplates.value.some(x => x.issn === j.issn)) {
                ElementPlus.ElMessage.info(configStore.currentLang === 'zh' ? '该期刊已在列表中' : 'Journal already added');
            } else {
                journalTemplates.value.push({ key: 'cat_' + j.issn, name: j.title, issn: j.issn, enabled: true });
            }
        }
        pickedIssn.value = '';
    }

    function removeJournal(i) {
        journalTemplates.value.splice(i, 1);
    }

    async function doGenerate() {
        if (!description.value.trim()) return;
        generating.value = true;
        try {
            plan.value = await profileStore.generatePlan(description.value);
        } catch (e) {
            ElementPlus.ElMessage.error(e.message || '生成失败');
        } finally {
            generating.value = false;
        }
    }

    const visibleKeywords = computed(() => {
        const kws = plan.value?.keywords || [];
        return showAllKeywords.value ? kws : kws.slice(0, 4);
    });
    function addKeyword() {
        const kw = keywordInput.value.trim();
        if (!kw) return;
        if (!plan.value.keywords) plan.value.keywords = [];
        if (!plan.value.keywords.includes(kw)) plan.value.keywords.push(kw);
        keywordInput.value = '';
    }
    function removeKeyword(i) {
        if (plan.value && plan.value.keywords) plan.value.keywords.splice(i, 1);
    }

    async function save() {
        if (!name.value.trim() || !description.value.trim()) {
            ElementPlus.ElMessage.warning(configStore.currentLang === 'zh' ? '请填写名称与描述' : 'Name and description required');
            return;
        }
        saving.value = true;
        try {
            const data = {
                name: name.value.trim(),
                description: description.value.trim(),
                retrieval_plan: plan.value || undefined,
                journals: journalTemplates.value,
                sources: { arxiv: !!sources.arxiv, crossref: !!sources.crossref, s2: !!sources.s2 }
            };
            if (props.editing) {
                await profileStore.updateProfile(props.editing, data);
            } else {
                await profileStore.createProfile(data);
            }
            emit('saved');
            emit('update:show', false);
        } catch (e) {
            ElementPlus.ElMessage.error(e.message || '保存失败');
        } finally {
            saving.value = false;
        }
    }

    const t = (key, params) => configStore.t(key, params);
    const currentLang = configStore.currentLang;
    return { show: props.show, editing: props.editing, name, description, plan, generating, saving,
             sources, journalTemplates, doSearchJournals, catalogItems, catalogLoading,
             journalSyncing, journalCatalogCount, pickedIssn, addFromCatalog, removeJournal,
             doGenerate, save, t, keywordInput, addKeyword, removeKeyword,
             visibleKeywords, showAllKeywords, planOpen, kwOpen, currentLang };
};
