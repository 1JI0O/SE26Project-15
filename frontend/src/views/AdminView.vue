<template>
  <section class="admin-page">
    <header class="admin-header">
      <div>
        <h1>平台管理</h1>
        <p class="hint">管理 TraceLab 云端账号、配额与运维任务。不提供项目正文读取。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-row :gutter="12" class="metrics">
      <el-col v-for="(value, key) in metrics" :key="key" :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="metric-card">
          <el-statistic :title="metricLabels[key] ?? key" :value="value" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header><strong>账号管理</strong></template>
      <el-table :data="users" v-loading="loading" empty-text="暂无用户">
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column prop="display_name" label="名称" width="140" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="已验证" width="90">
          <template #default="scope">{{ scope.row.email_verified ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="scope">{{ scope.row.is_platform_admin ? '管理员' : '用户' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="scope">
            <el-button text @click="toggle(scope.row)">
              {{ scope.row.status === 'active' ? '停用' : '启用' }}
            </el-button>
            <el-button text type="danger" @click="forceLogout(scope.row)">强制下线</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header><strong>工作区配额</strong></template>
      <el-table :data="workspaces" v-loading="loading" empty-text="暂无工作区">
        <el-table-column prop="name" label="工作区" min-width="160" />
        <el-table-column prop="owner_email" label="所有者" min-width="180" />
        <el-table-column label="配额" width="120">
          <template #default="scope">{{ formatGiB(scope.row.storage_limit_bytes) }} GiB</template>
        </el-table-column>
        <el-table-column prop="workspace_seq" label="同步序号" width="100" />
        <el-table-column label="调整配额" width="280" fixed="right">
          <template #default="scope">
            <div class="quota-row">
              <el-input-number
                v-model="quotaDrafts[scope.row.workspace_id]"
                :min="1"
                :max="100"
                size="small"
              />
              <span>GiB</span>
              <el-button size="small" @click="updateQuota(scope.row)">保存</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header>
        <div class="card-header">
          <strong>后台任务</strong>
          <div class="actions">
            <el-button type="warning" @click="queueGc">墓碑与 Blob GC</el-button>
            <el-button type="warning" @click="queueEventCompaction">压缩同步事件</el-button>
          </div>
        </div>
      </template>
      <el-table :data="jobs" empty-text="暂无任务">
        <el-table-column prop="job_type" label="类型" width="180" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="attempt_count" label="尝试" width="80" />
        <el-table-column prop="last_error" label="错误" min-width="220" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" width="190" />
      </el-table>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header><strong>脱敏审计记录</strong></template>
      <el-table :data="audit" empty-text="暂无审计">
        <el-table-column prop="created_at" label="时间" width="190" />
        <el-table-column prop="action" label="动作" width="200" />
        <el-table-column prop="actor_id" label="操作者 UUID" min-width="160" show-overflow-tooltip />
        <el-table-column prop="target" label="目标" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { cloudHttp } from '@/api/http'
import type { CloudUser } from '@/types/cloud'

type AdminWorkspace = {
  workspace_id: string
  name: string
  owner_email: string
  storage_limit_bytes: number
  workspace_seq: number
}

type AdminJob = {
  job_id: string
  job_type: string
  status: string
  attempt_count: number
  last_error: string | null
  created_at: string
}

const users = ref<CloudUser[]>([])
const workspaces = ref<AdminWorkspace[]>([])
const jobs = ref<AdminJob[]>([])
const metrics = ref<Record<string, number>>({})
const audit = ref<Array<Record<string, unknown>>>([])
const loading = ref(false)
const quotaDrafts = reactive<Record<string, number>>({})

const metricLabels: Record<string, string> = {
  users: '用户',
  workspaces: '工作区',
  ready_blobs: 'Blob',
  queued_jobs: '排队任务',
  disk_percent: '磁盘 %',
  disk_warning: '80% 告警',
  uploads_blocked: '90% 停传',
}

function formatGiB(bytes: number) {
  return Math.round((bytes / 1024 ** 3) * 10) / 10
}

async function load() {
  loading.value = true
  try {
    const [userResponse, workspaceResponse, metricResponse, auditResponse, jobResponse] =
      await Promise.all([
        cloudHttp.get<CloudUser[]>('/admin/users'),
        cloudHttp.get<AdminWorkspace[]>('/admin/workspaces'),
        cloudHttp.get<Record<string, number>>('/admin/metrics'),
        cloudHttp.get<Array<Record<string, unknown>>>('/admin/audit'),
        cloudHttp.get<AdminJob[]>('/admin/jobs'),
      ])
    users.value = userResponse.data
    workspaces.value = workspaceResponse.data
    metrics.value = metricResponse.data
    audit.value = auditResponse.data
    jobs.value = jobResponse.data
    for (const workspace of workspaces.value) {
      quotaDrafts[workspace.workspace_id] = Math.max(
        1,
        Math.round(workspace.storage_limit_bytes / 1024 ** 3),
      )
    }
  } catch {
    ElMessage.error('加载管理数据失败，请确认已用管理员账号登录')
  } finally {
    loading.value = false
  }
}

async function patchUser(user: CloudUser, payload: Record<string, unknown>) {
  const response = await cloudHttp.patch<CloudUser>(`/admin/users/${user.user_id}`, payload)
  users.value = users.value.map((item) =>
    item.user_id === user.user_id ? response.data : item,
  )
}

async function toggle(user: CloudUser) {
  await patchUser(user, { status: user.status === 'active' ? 'disabled' : 'active' })
  ElMessage.success(user.status === 'active' ? '账号已停用' : '账号已启用')
}

async function forceLogout(user: CloudUser) {
  await patchUser(user, { force_logout: true })
  ElMessage.success('该账号的所有会话已撤销')
}

async function updateQuota(workspace: AdminWorkspace) {
  const gib = quotaDrafts[workspace.workspace_id] ?? 5
  await cloudHttp.patch(`/admin/workspaces/${workspace.workspace_id}/quota`, {
    storage_limit_bytes: gib * 1024 ** 3,
  })
  workspace.storage_limit_bytes = gib * 1024 ** 3
  ElMessage.success('配额已更新')
}

async function queueGc() {
  await cloudHttp.post('/admin/maintenance/gc')
  ElMessage.success('维护任务已入队')
  await load()
}

async function queueEventCompaction() {
  await cloudHttp.post('/admin/maintenance/compact-events')
  ElMessage.success('事件压缩任务已入队')
  await load()
}

onMounted(load)
</script>

<style scoped>
.admin-page {
  width: min(1200px, calc(100% - 36px));
  margin: 24px auto 40px;
}

.admin-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.admin-header h1 {
  margin: 0;
  font-size: 22px;
}

.hint {
  margin: 6px 0 0;
  color: #607080;
  font-size: 13px;
}

.metrics,
.section {
  margin-bottom: 16px;
}

.metric-card {
  margin-bottom: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.actions {
  display: flex;
  gap: 8px;
}

.quota-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
