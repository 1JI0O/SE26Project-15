<template>
  <div :class="['app-shell', { 'workspace-mode': isWorkspace }]">
    <header class="topbar">
      <router-link class="brand" to="/">
        <span class="brand-mark">T</span>
        <strong>TraceLab</strong>
      </router-link>
      <div class="topbar-actions">
        <el-tooltip content="集成设置" placement="bottom">
          <el-button text :icon="Setting" aria-label="集成设置" @click="settingsOpen = true" />
        </el-tooltip>
      </div>
    </header>
    <main class="workspace">
      <slot />
    </main>
    <IntegrationSettingsDialog v-model="settingsOpen" />
  </div>
</template>

<script setup lang="ts">
import { Setting } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import IntegrationSettingsDialog from '@/features/settings/IntegrationSettingsDialog.vue'

const settingsOpen = ref(false)
const route = useRoute()
const isWorkspace = computed(() => route.name === 'workspace')
</script>

<style scoped>
.app-shell {
  display: grid;
  grid-template-rows: 38px minmax(0, 1fr);
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  background: #eef1f4;
  color: #24313d;
}

.topbar {
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 38px;
  padding: 0 10px;
  border-bottom: 1px solid #d8dee6;
  background: #f7f8fa;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: inherit;
  font-size: 13px;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 5px;
  background: #1f8f78;
  color: white;
  font-size: 12px;
  font-weight: 700;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.workspace {
  width: 100%;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: auto;
}

.workspace-mode {
  background: #eef1f4;
}

.workspace-mode .workspace {
  overflow: hidden;
}

@media (max-width: 720px) {
  .topbar {
    padding: 0 8px;
  }
}
</style>
