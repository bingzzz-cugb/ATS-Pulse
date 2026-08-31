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
                this.profiles = res.ok ? await res.json() : [];
            } catch (e) {
                console.error('Failed to fetch profiles:', e);
            } finally {
                this.loading = false;
            }
        },
        async generatePlan(description) {
            const res = await API.config.profiles.generate(description);
            if (!res.ok) throw new Error('生成失败');
            return res.json();
        },
        async createProfile(data) {
            const res = await API.config.profiles.create(data);
            if (!res.ok) throw new Error('创建失败');
            const profile = await res.json();
            this.profiles.push(profile);
            return profile;
        },
        async updateProfile(id, data) {
            const res = await API.config.profiles.update(id, data);
            if (!res.ok) throw new Error('更新失败');
            const profile = await res.json();
            const idx = this.profiles.findIndex(p => p.id === id);
            if (idx >= 0) this.profiles[idx] = profile;
            return profile;
        },
        async removeProfile(id) {
            const res = await API.config.profiles.remove(id);
            if (!res.ok) throw new Error('删除失败');
            this.profiles = this.profiles.filter(p => p.id !== id);
        }
    }
});
