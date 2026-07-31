<template>
  <section class="conflict-page">
    <header>
      <div>
        <h1>同步冲突中心</h1>
        <p>未解决冲突不会丢弃或覆盖本地操作。选择后会在下一轮同步应用。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>
    <el-empty v-if="!loading && !conflicts.length" description="没有待处理冲突" />
    <el-card v-for="conflict in conflicts" :key="conflict.conflict_id" class="conflict-card">
      <template #header>
        <strong>{{ labels[conflict.entity_type] ?? conflict.entity_type }}</strong>
        <code>{{ conflict.entity_public_id }}</code>
      </template>
      <el-table :data="diffRows(conflict)" size="small" border>
        <el-table-column prop="field" label="字段" width="180" />
        <el-table-column label="本地版本">
          <template #default="scope"><pre>{{ format(scope.row.local) }}</pre></template>
        </el-table-column>
        <el-table-column label="云端版本">
          <template #default="scope"><pre>{{ format(scope.row.remote) }}</pre></template>
        </el-table-column>
      </el-table>
      <div class="actions">
        <el-button type="primary" @click="resolve(conflict, 'keep_local')">保留本地决定</el-button>
        <el-button @click="resolve(conflict, 'use_remote')">采用云端版本</el-button>
        <el-button
          v-if="fileTypes.has(conflict.entity_type)"
          @click="resolve(conflict, 'keep_both')"
        >保留两个文件版本</el-button>
      </div>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { cloudHttp, localHttp } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'

type Conflict = {
  conflict_id: string
  entity_type: string
  entity_public_id: string
  local: Record<string, unknown>
  remote: Record<string, unknown>
}

const labels: Record<string, string> = {
  project: '项目字段',
  trace_link: 'TraceLink 人工决定',
  paper_document: '论文文件',
  code_repository: '代码仓库',
  code_edit: '代码编辑版本',
}
const fileTypes = new Set(['paper_document', 'code_repository'])
const conflicts = ref<Conflict[]>([])
const loading = ref(false)
const auth = useAuthStore()
const sync = useSyncStore()

function diffRows(conflict: Conflict) {
  const fields = new Set([...Object.keys(conflict.local), ...Object.keys(conflict.remote)])
  return [...fields]
    .filter((field) => JSON.stringify(conflict.local[field]) !== JSON.stringify(conflict.remote[field]))
    .map((field) => ({ field, local: conflict.local[field], remote: conflict.remote[field] }))
}

function format(value: unknown) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

async function load() {
  if (!auth.workspace) return
  loading.value = true
  try {
    const response = await localHttp.get<Conflict[]>('/local-sync/conflicts', {
      params: { workspace_id: auth.workspace.workspace_id },
    })
    conflicts.value = response.data
    sync.conflictCount = response.data.length
  } finally {
    loading.value = false
  }
}

async function resolve(conflict: Conflict, resolution: 'keep_local' | 'use_remote' | 'keep_both') {
  try {
    if (resolution === 'use_remote' && fileTypes.has(conflict.entity_type)) {
      const blobId = conflict.remote.blob_id
      if (typeof blobId === 'string') {
        const downloaded = await cloudHttp.get<ArrayBuffer>(`/blobs/${blobId}/download`, {
          responseType: 'arraybuffer',
        })
        await localHttp.put(
          `/local-sync/conflicts/${conflict.conflict_id}/blob`,
          downloaded.data,
          { headers: { 'Content-Type': 'application/octet-stream' } },
        )
      }
    }
    await localHttp.post(`/local-sync/conflicts/${conflict.conflict_id}/resolve`, { resolution })
    await load()
    if (resolution !== 'use_remote') await sync.sync()
    ElMessage.success('冲突处理结果已保存')
  } catch {
    ElMessage.error('冲突处理失败，原操作仍被保留')
  }
}

onMounted(load)
</script>

<style scoped>
.conflict-page { width: min(1100px, calc(100% - 40px)); margin: 24px auto; }
header { display: flex; align-items: start; justify-content: space-between; margin-bottom: 18px; }
h1 { margin: 0 0 6px; font-size: 22px; }
p { margin: 0; color: #64748b; }
.conflict-card { margin-bottom: 16px; }
.conflict-card :deep(.el-card__header) { display: flex; justify-content: space-between; }
code { color: #64748b; }
pre { max-height: 180px; margin: 0; overflow: auto; white-space: pre-wrap; word-break: break-word; }
.actions { display: flex; gap: 8px; margin-top: 14px; }
</style>
