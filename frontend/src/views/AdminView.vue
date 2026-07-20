<template>
  <section class="admin-page">
    <h1>平台管理</h1>
    <el-row :gutter="12" class="metrics">
      <el-col v-for="(value, key) in metrics" :key="key" :span="4">
        <el-statistic :title="metricLabels[key] ?? key" :value="value" />
      </el-col>
    </el-row>
    <el-card>
      <template #header><strong>用户状态与会话</strong></template>
      <el-table :data="users" v-loading="loading">
        <el-table-column prop="email" label="邮箱" />
        <el-table-column prop="display_name" label="名称" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="email_verified" label="已验证" width="90" />
        <el-table-column label="操作" width="230">
          <template #default="scope">
            <el-button text @click="toggle(scope.row)">{{ scope.row.status === 'active' ? '停用' : '启用' }}</el-button>
            <el-button text type="danger" @click="forceLogout(scope.row)">强制下线</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-card class="maintenance">
      <template #header><strong>配额与维护</strong></template>
      <el-input v-model="workspaceId" placeholder="workspace UUID" />
      <el-input-number v-model="quotaGiB" :min="1" :max="100" /> GiB
      <el-button @click="updateQuota">更新配额</el-button>
      <el-button type="warning" @click="queueGc">执行墓碑与 Blob GC</el-button>
      <el-button type="warning" @click="queueEventCompaction">压缩已确认同步事件</el-button>
    </el-card>
    <el-card>
      <template #header><strong>脱敏审计记录</strong></template>
      <el-table :data="audit">
        <el-table-column prop="created_at" label="时间" width="190" />
        <el-table-column prop="action" label="动作" width="200" />
        <el-table-column prop="actor_id" label="操作者 UUID" />
        <el-table-column prop="target" label="目标" />
      </el-table>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { cloudHttp } from '@/api/http'
import type { CloudUser } from '@/types/cloud'

const users = ref<CloudUser[]>([])
const metrics = ref<Record<string, number>>({})
const audit = ref<Array<Record<string, unknown>>>([])
const loading = ref(false)
const workspaceId = ref('')
const quotaGiB = ref(5)
const metricLabels: Record<string, string> = {
  users: '用户', workspaces: '工作区', ready_blobs: 'Blob', queued_jobs: '排队任务', disk_percent: '磁盘 %', disk_warning: '80% 告警', uploads_blocked: '90% 停传',
}
async function load() {
  loading.value = true
  try {
    const [userResponse, metricResponse, auditResponse] = await Promise.all([
      cloudHttp.get<CloudUser[]>('/admin/users'),
      cloudHttp.get<Record<string, number>>('/admin/metrics'),
      cloudHttp.get<Array<Record<string, unknown>>>('/admin/audit'),
    ])
    users.value = userResponse.data
    metrics.value = metricResponse.data
    audit.value = auditResponse.data
  } finally { loading.value = false }
}
async function patchUser(user: CloudUser, payload: Record<string, unknown>) {
  const response = await cloudHttp.patch<CloudUser>(`/admin/users/${user.user_id}`, payload)
  users.value = users.value.map((item) => item.user_id === user.user_id ? response.data : item)
}
async function toggle(user: CloudUser) { await patchUser(user, { status: user.status === 'active' ? 'disabled' : 'active' }) }
async function forceLogout(user: CloudUser) { await patchUser(user, { force_logout: true }); ElMessage.success('该账号的所有会话已撤销') }
async function updateQuota() {
  if (!workspaceId.value) return
  await cloudHttp.patch(`/admin/workspaces/${workspaceId.value}/quota`, { storage_limit_bytes: quotaGiB.value * 1024 ** 3 })
  ElMessage.success('配额已更新')
}
async function queueGc() { await cloudHttp.post('/admin/maintenance/gc'); ElMessage.success('维护任务已入队') }
async function queueEventCompaction() { await cloudHttp.post('/admin/maintenance/compact-events'); ElMessage.success('事件压缩任务已入队') }
onMounted(load)
</script>

<style scoped>
.admin-page { width: min(1200px, calc(100% - 36px)); margin: 24px auto; }
.metrics, .maintenance, .admin-page > .el-card { margin-bottom: 16px; }
.maintenance :deep(.el-card__body) { display: flex; align-items: center; gap: 10px; }
.maintenance .el-input { width: 360px; }
</style>
