<template>
  <div :class="['app-shell', { 'workspace-mode': isWorkspace }]">
    <header class="topbar">
      <router-link class="brand" to="/">
        <span class="brand-mark">T</span>
        <strong>TraceLab</strong>
      </router-link>
      <div class="topbar-actions">
        <router-link
          v-if="localCloudSyncAvailable && sync.conflictCount"
          class="account-link conflict-link"
          to="/conflicts"
        >冲突中心（{{ sync.conflictCount }}）</router-link>
        <div v-if="runtimeMode !== 'cloud'" class="topbar-icon-actions">
          <el-tooltip content="Agent 运行队列" placement="bottom">
            <el-button class="queue-button" text :icon="Tickets" aria-label="Agent 运行队列" @click="queueOpen = true" />
          </el-tooltip>
          <el-tooltip content="集成设置" placement="bottom">
            <el-button text :icon="Setting" aria-label="集成设置" @click="settingsOpen = true" />
          </el-tooltip>
        </div>
        <router-link v-if="auth.authenticated" to="/account" class="account-link">
          {{ auth.user?.display_name || auth.user?.email }}
        </router-link>
        <router-link v-if="auth.user?.is_platform_admin" to="/admin" class="account-link">管理</router-link>
        <el-button v-if="auth.authenticated" text @click="logout">退出</el-button>
        <router-link v-else-if="cloudConfigured" to="/login" class="account-link">登录</router-link>
      </div>
    </header>
    <main class="workspace">
      <slot />
    </main>
    <AgentQueueDialog v-model="queueOpen" />
    <IntegrationSettingsDialog v-model="settingsOpen" />
  </div>
</template>

<script setup lang="ts">
import { Setting, Tickets } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { cloudConfigured, localCloudSyncAvailable, runtimeMode } from '@/api/http'
import AgentQueueDialog from '@/features/agent/AgentQueueDialog.vue'
import IntegrationSettingsDialog from '@/features/settings/IntegrationSettingsDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'

const queueOpen = ref(false)
const settingsOpen = ref(false)
const route = useRoute()
const router = useRouter()
const isWorkspace = computed(() => route.name === 'workspace')
const auth = useAuthStore()
const sync = useSyncStore()

// Single-device login: when this account signs in on another device, this
// device's next cloud request is rejected and the session is cleared. Surface
// a clear notice and return to the login screen.
watch(
  () => auth.sessionEndedElsewhere,
  (ended) => {
    if (!ended) return
    ElMessage.warning('账号已在其他设备登录，本设备已退出登录')
    auth.sessionEndedElsewhere = false
    if (route.name !== 'login') void router.push('/login')
  },
)

onMounted(() => {
  if (localCloudSyncAvailable && auth.authenticated) void sync.refreshConflicts()
})

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
  gap: 12px;
}

.topbar-icon-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.topbar-icon-actions :deep(.el-button) {
  display: inline-grid;
  width: 24px;
  height: 24px;
  min-height: 24px;
  padding: 0;
  place-items: center;
}

.topbar-icon-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.topbar-icon-actions :deep(.el-icon) {
  display: inline-flex;
  width: 16px;
  height: 16px;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  line-height: 1;
}

.topbar-icon-actions :deep(.queue-button .el-icon) {
  transform: translateY(-0.5px);
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
