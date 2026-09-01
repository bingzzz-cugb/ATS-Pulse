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
                <el-form-item :label="t('settings.s2ApiKey')">
                    <el-input v-model="settingsConfig.s2_api_key" type="password" show-password>
                        <template #append>
                            <el-button type="primary" @click="saveS2Key" :loading="savingSettings">{{ t('settings.updateKey') }}</el-button>
                        </template>
                    </el-input>
                    <p style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">{{ t('settings.s2ApiKeyHint') }}</p>
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
            <!-- arXiv 筛选标签（全局领域过滤，合并于检索领域下） -->
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--bg-subtle); border-radius: 8px; margin-bottom: 12px;">
                <div style="min-width: 0;">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">
                        {{ currentLang === 'zh' ? 'arXiv 筛选标签' : 'arXiv field tags' }}
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <template v-if="selectedFieldNames.length">{{ selectedFieldNames.join('、') }}</template>
                        <template v-else><span style="color: var(--text-muted);">{{ currentLang === 'zh' ? '未选择（默认 cs.CV）' : 'Not set (default cs.CV)' }}</span></template>
                    </div>
                </div>
                <el-button size="small" @click="openFieldSelector">
                    <el-icon><Edit /></el-icon> {{ currentLang === 'zh' ? '选择' : 'Select' }}
                </el-button>
            </div>
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
    </div>
</el-drawer>
`;

const SettingsDrawerSetup = (props) => {
    const configStore = useConfigStore();
    const profileStore = useProfileStore();

    const { settingsConfig, savingSettings, testingAI, currentLang, currentTheme, allCategories } = storeToRefs(configStore);
    const { t, saveApiKey, saveS2Key, testAIConnection, setLanguage, setTheme, openFieldSelector } = configStore;

    const selectedFieldNames = computed(() =>
        (settingsConfig.value?.selected_fields || []).slice(0, 5).map((id) => allCategories.value[id]?.name || id)
    );

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
        saveS2Key,
        testAIConnection,
        aiLanguageOptions,
        onLanguageChange,
        onThemeChange,
        profileStore,
        removeProfile,
        dispatchProfileCreate, dispatchProfileEdit,
        selectedFieldNames, openFieldSelector
    };
};
