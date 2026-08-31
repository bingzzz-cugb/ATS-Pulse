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
                    <div v-for="(item, i) in plan.arxiv_queries" :key="i" style="margin-bottom: 4px;">
                        <el-input size="small" v-model="plan.arxiv_queries[i]"></el-input>
                    </div>
                    <el-input size="small" v-model="plan.s2_query" :placeholder="t('settings.profileS2Ph')" style="margin-top: 4px;"></el-input>
                </div>
            </el-form-item>
            <el-form-item :label="t('settings.profileJournals')">
                <div style="width: 100%; display: flex; flex-wrap: wrap; gap: 8px;">
                    <el-checkbox v-for="j in journalTemplates" :key="j.issn" v-model="j.enabled">{{ j.name }}</el-checkbox>
                    <el-input v-model="customJournalName" size="small" :placeholder="t('settings.profileJournalName')" style="width: 160px;"></el-input>
                    <el-input v-model="customJournalIssn" size="small" placeholder="ISSN" style="width: 130px;"></el-input>
                    <el-button size="small" @click="addCustomJournal">{{ t('common.add') }}</el-button>
                </div>
            </el-form-item>
            <el-form-item :label="t('settings.profileSources')">
                <el-checkbox v-model="sources.arxiv">arXiv</el-checkbox>
                <el-checkbox v-model="sources.crossref">Crossref</el-checkbox>
                <el-checkbox v-model="sources.s2">Semantic Scholar</el-checkbox>
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
    const customJournalName = ref('');
    const customJournalIssn = ref('');

    watch(() => props.show, (v) => {
        if (!v) return;
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
            return;
        }
        const p = profileStore.profiles.find(x => x.id === editing);
        if (!p) return;
        name.value = p.name;
        description.value = p.description || '';
        plan.value = p.retrieval_plan || null;
        sources.arxiv = p.sources.arxiv !== false;
        sources.crossref = p.sources.crossref !== false;
        sources.s2 = p.sources.s2 !== false;
        journalTemplates.value = (p.journals && p.journals.length ? p.journals : journalTemplates.value).map(j => ({
            key: j.key, name: j.name, issn: j.issn, enabled: j.enabled !== false
        }));
    });

    function addCustomJournal() {
        const issn = customJournalIssn.value.trim();
        const nm = customJournalName.value.trim();
        if (!issn || !nm) return;
        journalTemplates.value.push({ key: 'custom_' + issn, name: nm, issn, enabled: true });
        customJournalIssn.value = '';
        customJournalName.value = '';
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
    return { show: props.show, editing: props.editing, name, description, plan, generating, saving,
             sources, journalTemplates, customJournalName, customJournalIssn,
             addCustomJournal, doGenerate, save, t };
};
