<template>
  <div :class="['app-shell', { 'workspace-mode': isWorkspace }]">
    <header class="topbar">
      <router-link class="brand" to="/">
        <span class="brand-mark">T</span>
        <strong>TraceLab</strong>
      </router-link>
      <div class="topbar-actions">
        <router-link
          v-if="localCloudSyncAvailable && auth.authenticated && auth.verified"
          class="account-link"
          to="/cloud-projects"
        >云端项目</router-link>
        <el-button
          v-if="localCloudSyncAvailable && auth.authenticated && auth.verified"
          text
          :loading="sync.syncing"
          @click="runSync"
        >
          云同步<span v-if="sync.conflictCount">（{{ sync.conflictCount }} 个冲突）</span>
        </el-button>
        <router-link
          v-if="localCloudSyncAvailable && sync.conflictCount"
          class="account-link conflict-link"
          to="/conflicts"
        >冲突中心</router-link>
        <el-tooltip v-if="runtimeMode !== 'cloud'" content="集成设置" placement="bottom">
          <el-button text :icon="Setting" aria-label="集成设置" @click="settingsOpen = true" />
        </el-tooltip>
        <router-link v-if="auth.authenticated" to="/account" class="account-link">
          {{ auth.user?.display_name || auth.user?.email }}
        </router-link>
        <router-link v-if="auth.user?.is_platform_admin" to="/admin" class="account-link">管理</router-link>
        <el-button v-if="auth.authenticated" text @click="logout">退出</el-button>
        <router-link v-else-if="cloudConfigured" to="/login" class="account-link">登录云端</router-link>
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
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { cloudConfigured, localCloudSyncAvailable, runtimeMode } from '@/api/http'
import IntegrationSettingsDialog from '@/features/settings/IntegrationSettingsDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'

const settingsOpen = ref(false)
const route = useRoute()
const isWorkspace = computed(() => route.name === 'workspace')
const auth = useAuthStore()
const sync = useSyncStore()

onMounted(() => {
  if (localCloudSyncAvailable && auth.authenticated) void sync.refreshConflicts()
})

async function runSync() {
  try {
    await sync.sync()
    ElMessage.success('云同步完成')
  } catch {
    ElMessage.error('云同步失败，本地工作不受影响')
  }
}

async function logout() {
  await auth.logout()
  window.location.assign('/login')
}
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

.account-link {
  color: #425466;
  font-size: 12px;
  text-decoration: none;
}

.conflict-link {
  color: #b45309;
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
