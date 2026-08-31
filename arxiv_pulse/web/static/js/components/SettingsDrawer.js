const SettingsDrawerTemplate = `
<el-drawer :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" :title="t('settings.title')" size="480px" class="settings-drawer">
    <div style="padding: 24px;">
        <!-- UI Language -->
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; padding: 12px 16px; background: var(--bg-subtle); border-radius: 10px;">
            <span>
                <span :style="{ fontWeight: currentLang === 'zh' ? 600 : 400, opacity: currentLang === 'zh' ? 1 : 0.5 }">界面语言</span>
                <span style="margin: 0 6px; opacity: 0.3;">/</span>
                <span :style="{ fontWeight: currentLang === 'en' ? 600 : 400, opacity: currentLang === 'en' ? 1 : 0.5 }">UI Language</span>
            </span>
            <el-radio-group :model-value="currentLang" size="small" @change="onLanguageChange">
                <el-radio-button label="zh">中文</el-radio-button>
                <el-radio-button label="en">EN</el-radio-button>
            </el-radio-group>
        </div>
        
        <!-- Theme Mode -->
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; padding: 12px 16px; background: var(--bg-subtle); border-radius: 10px;">
            <span>
                <span :style="{ fontWeight: currentLang === 'zh' ? 600 : 400, opacity: currentLang === 'zh' ? 1 : 0.5 }">颜色模式</span>
                <span style="margin: 0 6px; opacity: 0.3;">/</span>
                <span :style="{ fontWeight: currentLang === 'en' ? 600 : 400, opacity: currentLang === 'en' ? 1 : 0.5 }">Theme</span>
            </span>
            <el-radio-group :model-value="currentTheme" size="small" @change="onThemeChange">
                <el-radio-button label="light">{{ currentLang === 'zh' ? '亮色' : 'Light' }}</el-radio-button>
                <el-radio-button label="dark">{{ currentLang === 'zh' ? '暗色' : 'Dark' }}</el-radio-button>
            </el-radio-group>
        </div>
        
        <div class="settings-section">
            <h3>{{ t('settings.aiConfig') }}</h3>
            <el-form label-position="top">
                <el-form-item :label="t('settings.apiBaseUrl')">
                    <el-input v-model="settingsConfig.ai_base_url" />
                </el-form-item>
                <el-form-item :label="t('settings.apiKey')">
                    <el-input v-model="settingsConfig.ai_api_key" type="password" show-password>
                        <template #append>
                            <el-button type="primary" @click="saveApiKey" :loading="savingSettings">{{ t('settings.updateKey') }}</el-button>
                        </template>
                    </el-input>
                </el-form-item>
                <el-form-item :label="t('settings.modelName')">
                    <el-input v-model="settingsConfig.ai_model" />
                </el-form-item>
                <el-form-item :label="t('settings.aiLanguage')">
                    <el-select v-model="settingsConfig.translate_language" style="width: 100%;">
                        <el-option v-for="lang in aiLanguageOptions" :key="lang.value" :label="lang.label" :value="lang.value" />
                    </el-select>
                    <p style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">{{ t('settings.aiLanguageHint') }}</p>
                </el-form-item>
                <el-form-item>
                    <el-button @click="testAIConnection" :loading="testingAI">{{ t('settings.testConnection') }}</el-button>
                </el-form-item>
            </el-form>
        </div>

        <div class="settings-section">
            <h3>{{ t('settings.profilesTitle') }}</h3>
            <p style="color: var(--text-muted); font-size: 12px; margin-bottom: 12px;">
                {{ t('settings.profilesHint') }}
            </p>
            <div v-for="p in profileStore.profiles" :key="p.id"
                 style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: var(--bg-subtle); border-radius: 8px; margin-bottom: 8px; cursor: pointer;"
                 @click="dispatchProfileEdit(p.id)">
                <div style="flex: 1;">
                    <div style="font-size: 13px; font-weight: 600;">{{ p.name }}
                        <el-tag v-if="!p.enabled" size="small" type="info" style="margin-left: 6px;">{{ currentLang === 'zh' ? '停用' : 'Disabled' }}</el-tag>
                    </div>
                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">
                        {{ (p.retrieval_plan?.arxiv_queries || []).length }} {{ t('settings.profileQueries') }} · {{ p.journals?.filter?.(j => j.enabled)?.length || 0 }} {{ t('settings.profileJournals') }} · {{ Object.keys(p.sources || {}).filter(k => p.sources[k]).length }} {{ t('settings.profileSourcesShort') }}
                    </div>
                </div>
                <el-button text size="small" @click.stop="removeProfile(p.id)">{{ t('common.delete') }}</el-button>
            </div>
            <el-button type="primary" plain size="small" style="width: 100%;" @click="dispatchProfileCreate">
                <el-icon><Plus /></el-icon> {{ t('settings.profilesCreate') }}
            </el-button>
        </div>

        <div class="settings-section">
            <h3>{{ t('settings.syncSettings') }}</h3>
            <el-form label-position="top">
                <el-form-item :label="t('settings.yearsBack')">
                    <el-select v-model="settingsConfig.years_back" style="width: 100%;">
                        <el-option v-for="item in initYearOptions" :key="item.value" :label="item.label" :value="item.value" />
                    </el-select>
                </el-form-item>
                <el-form-item :label="t('settings.maxResultsPerField')">
                    <el-input-number v-model="settingsConfig.arxiv_max_results_per_field" :min="1000" :max="50000" :step="1000" style="width: 100%;" />
                </el-form-item>
                <el-form-item :label="t('settings.arxivMaxResults')">
                    <el-input-number v-model="settingsConfig.arxiv_max_results" :min="10000" :max="200000" :step="10000" style="width: 100%;" />
                </el-form-item>
                <el-form-item :label="t('settings.recentPapersLimit')">
                    <el-input-number v-model="settingsConfig.recent_papers_limit" :min="20" :max="200" :step="10" style="width: 100%;" />
                </el-form-item>
                <el-form-item :label="t('settings.searchLimit')">
                    <el-input-number v-model="settingsConfig.search_limit" :min="5" :max="100" :step="5" style="width: 100%;" />
                </el-form-item>
            </el-form>
        </div>
    </div>
</el-drawer>
`;

const SettingsDrawerSetup = (props) => {
    const configStore = useConfigStore();
    const profileStore = useProfileStore();

    const { settingsConfig, savingSettings, testingAI, currentLang, currentTheme } = storeToRefs(configStore);
    const { t, saveApiKey, testAIConnection, setLanguage, setTheme } = configStore;

    onMounted(() => {
        profileStore.fetchProfiles();
    });

    function dispatchProfileCreate() {
        window.dispatchEvent(new CustomEvent('open-profile-create'));
    }

    function dispatchProfileEdit(id) {
        window.dispatchEvent(new CustomEvent('open-profile-edit', { detail: id }));
    }

    async function removeProfile(id) {
        const configForMsg = configStore.currentLang === 'zh' ? '删除该检索领域档案？' : 'Delete this research profile?';
        try {
            await ElementPlus.ElMessageBox.confirm(configForMsg, '确认', { type: 'warning' });
            await profileStore.removeProfile(id);
            ElementPlus.ElMessage.success(configStore.currentLang === 'zh' ? '已删除' : 'Deleted');
        } catch (e) {
            if (e !== 'cancel') ElementPlus.ElMessage.error(configStore.currentLang === 'zh' ? '删除失败' : 'Delete failed');
        }
    }
    
    const aiLanguageOptions = [
        { value: 'zh', label: '中文' },
        { value: 'en', label: 'English' },
        { value: 'ru', label: 'Русский' },
        { value: 'fr', label: 'Français' },
        { value: 'de', label: 'Deutsch' },
        { value: 'es', label: 'Español' },
        { value: 'ar', label: 'العربية' }
    ];
    
    const initYearOptions = computed(() => {
        const isZh = currentLang.value === 'zh';
        return [
            { value: 1, label: isZh ? '1 年' : '1 year' },
            { value: 2, label: isZh ? '2 年' : '2 years' },
            { value: 3, label: isZh ? '3 年' : '3 years' },
            { value: 5, label: isZh ? '5 年（推荐）' : '5 years (Recommended)' },
            { value: 10, label: isZh ? '10 年' : '10 years' }
        ];
    });
    
    const onLanguageChange = (lang) => {
        setLanguage(lang);
        if (settingsConfig.value) {
            settingsConfig.value.ui_language = lang;
        }
    };
    
    const onThemeChange = (theme) => {
        setTheme(theme);
    };
    
    return {
        settingsConfig,
        savingSettings,
        testingAI,
        currentLang,
        currentTheme,
        t,
        saveApiKey,
        testAIConnection,
        aiLanguageOptions,
        initYearOptions,
        onLanguageChange,
        onThemeChange,
        profileStore,
        removeProfile,
        dispatchProfileCreate, dispatchProfileEdit
    };
};
