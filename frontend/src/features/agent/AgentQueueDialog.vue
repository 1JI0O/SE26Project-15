<template>
  <el-dialog
    :model-value="modelValue"
    title="Agent 运行队列"
    width="min(1080px, calc(100vw - 24px))"
    class="agent-queue-dialog"
    @update:model-value="emit('update:modelValue', $event)"
    @open="loadQueue"
  >
    <div class="queue-toolbar">
      <div class="queue-counts">
        <el-tag :type="queueStale ? 'danger' : queue?.active_count ? 'warning' : 'success'" effect="plain">
          {{ queueStale ? '后端断开' : `活跃 ${queue?.active_count ?? 0} / ${queue?.capacity ?? 0}` }}
        </el-tag>
        <el-tag v-if="queue?.stale_count" type="danger" effect="plain">
          僵住 {{ queue.stale_count }}
        </el-tag>
      </div>
      <el-tooltip content="刷新队列" placement="bottom">
        <el-button :icon="Refresh" text :loading="loading" aria-label="刷新队列" @click="loadQueue" />
      </el-tooltip>
    </div>

    <el-table
      v-loading="loading"
      :data="queue?.items ?? []"
      height="430"
      class="queue-table"
      empty-text="当前没有 Agent 在运行"
    >
      <el-table-column label="项目" width="155">
        <template #default="{ row }">
          <el-button class="project-button" link type="primary" @click="openProject(row.project_id)">
            {{ row.project_name }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="任务" width="125">
        <template #default="{ row }">
          <span class="kind-line">
            <el-icon><Monitor /></el-icon>
            {{ categoryLabel(row.category, row.kind) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="105">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status, row.stale, queueStale)" effect="plain">
            {{ statusLabel(row.status, row.stale, queueStale) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" min-width="250" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.summary || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="125">
        <template #default="{ row }">
          <span :title="formatFullTime(row.updated_at)">{{ formatAge(row.updated_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="82">
        <template #default="{ row }">
          {{ formatDuration(row.created_at, row.completed_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-tooltip content="打开项目" placement="bottom">
              <el-button :icon="Open" text aria-label="打开项目" @click="openProject(row.project_id)" />
            </el-tooltip>
            <el-tooltip content="停止任务" placement="bottom">
              <el-button
                :icon="VideoPause"
                text
                type="warning"
                :loading="operatingId === actionKey(row) + ':stop'"
                aria-label="停止任务"
                @click="stopItem(row)"
              />
            </el-tooltip>
            <el-tooltip content="删除任务" placement="bottom">
              <el-button
                :icon="Delete"
                text
                type="danger"
                :loading="operatingId === actionKey(row) + ':delete'"
                aria-label="删除任务"
                @click="deleteItem(row)"
              />
            </el-tooltip>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup lang="ts">
import { Delete, Monitor, Open, Refresh, VideoPause } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { deleteAgentQueueItem, getAgentQueue, stopAgentQueueItem } from '@/api/agent-api'
import type { AgentQueue, AgentQueueItem } from '@/types/agent'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const router = useRouter()
const loading = ref(false)
const queue = ref<AgentQueue | null>(null)
const queueStale = ref(false)
const operatingId = ref('')
let timer: number | null = null

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      void loadQueue()
      timer = window.setInterval(() => void loadQueue(true), 5000)
    } else {
      stopPolling()
    }
  },
)

onBeforeUnmount(stopPolling)

async function loadQueue(silent = false): Promise<void> {
  if (loading.value && silent) return
  loading.value = true
  try {
    queue.value = await getAgentQueue()
    queueStale.value = false
  } catch (cause) {
    queueStale.value = true
    if (!silent) ElMessage.error('Agent 队列加载失败，当前显示的是上一次状态')
    console.error(cause)
  } finally {
    loading.value = false
  }
}

function stopPolling(): void {
  if (timer !== null) window.clearInterval(timer)
  timer = null
}

async function openProject(projectId: number): Promise<void> {
  emit('update:modelValue', false)
  await router.push({ name: 'workspace', params: { id: String(projectId) } })
}

async function stopItem(row: AgentQueueItem): Promise<void> {
  const key = `${actionKey(row)}:stop`
  operatingId.value = key
  try {
    await stopAgentQueueItem(row.category, row.id)
    ElMessage.success('已请求停止任务')
    await loadQueue(true)
  } catch (cause) {
    ElMessage.error('停止任务失败')
    console.error(cause)
  } finally {
    if (operatingId.value === key) operatingId.value = ''
  }
}

async function deleteItem(row: AgentQueueItem): Promise<void> {
  try {
    await ElMessageBox.confirm('删除后该任务会从运行队列移除。', '删除任务', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const key = `${actionKey(row)}:delete`
  operatingId.value = key
  try {
    await deleteAgentQueueItem(row.category, row.id)
    ElMessage.success('任务已删除')
    await loadQueue(true)
  } catch (cause) {
    ElMessage.error('删除任务失败')
    console.error(cause)
  } finally {
    if (operatingId.value === key) operatingId.value = ''
  }
}

function actionKey(row: AgentQueueItem): string {
  return `${row.category}:${row.id}`
}

function categoryLabel(category: string, kind: string): string {
  const kindText = kind === 'trace' ? '追溯' : kind === 'architecture' ? '架构' : kind
  if (category === 'agent_analysis') return `Agent ${kindText}`
  if (category === 'agent_run') return 'Agent 对话'
  if (category === 'repository_analysis') return '代码分析'
  return '孤立运行'
}

function statusLabel(status: string, stale: boolean, disconnected: boolean): string {
  if (disconnected) return '状态过期'
  if (stale) return '疑似僵住'
  const labels: Record<string, string> = {
    queued: '排队',
    running: '运行中',
    validating: '验证中',
    cancelling: '中止中',
  }
  return labels[status] ?? status
}

function statusType(status: string, stale: boolean, disconnected: boolean): 'success' | 'warning' | 'danger' | 'info' {
  if (disconnected || stale) return 'danger'
  if (status === 'running' || status === 'validating') return 'warning'
  if (status === 'queued') return 'info'
  return 'success'
}

function parseTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)
}

function formatAge(value: string): string {
  const age = Math.max(0, Date.now() - parseTime(value).getTime())
  const minutes = Math.floor(age / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

function formatDuration(start: string, end: string | null): string {
  const elapsed = Math.max(0, (end ? parseTime(end).getTime() : Date.now()) - parseTime(start).getTime())
  const minutes = Math.floor(elapsed / 60000)
  if (minutes < 1) return '<1m'
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function formatFullTime(value: string): string {
  return parseTime(value).toLocaleString()
}
</script>

<style scoped>
.queue-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.queue-counts,
.kind-line,
.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.kind-line {
  color: #334155;
}

.project-button {
  max-width: 132px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-actions :deep(.el-button) {
  width: 28px;
  height: 28px;
  padding: 0;
}

:deep(.el-dialog__body) {
  padding-top: 8px;
}

:deep(.el-table__cell) {
  padding: 6px 0;
}
</style>