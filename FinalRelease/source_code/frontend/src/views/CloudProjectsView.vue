<template>
  <div class="cloud-projects">
    <el-card shadow="never">
      <template #header><div class="heading"><strong>云端项目</strong><span>{{ projects.length }} 个项目</span></div></template>
      <el-alert v-if="!auth.verified" title="请先验证邮箱，验证后才能创建和同步云端项目。" type="warning" show-icon />
      <el-form v-if="cloudWeb" class="create-row" inline @submit.prevent="create">
        <el-input v-model="name" placeholder="项目名称" />
        <el-input v-model="description" placeholder="项目说明（可选）" />
        <el-switch v-model="agentHistorySync" active-text="同步 Agent 历史" />
        <el-button type="primary" native-type="submit" :disabled="!auth.verified || !name.trim()">创建</el-button>
      </el-form>
      <el-table :data="projects" v-loading="loading" @row-dblclick="handleRowDoubleClick">
        <el-table-column prop="name" label="项目" />
        <el-table-column prop="description" label="说明" />
        <el-table-column prop="sync_mode" label="同步状态" width="140" />
        <el-table-column label="操作" width="240"><template #default="scope"><el-button v-if="hasLocalWorkspace" text type="primary" @click="download(scope.row)">下载到本地工作台</el-button><el-button v-else text type="primary" @click="open(scope.row)">打开</el-button><el-button v-if="auth.workspace?.role === 'owner'" text type="danger" @click="removeCloud(scope.row)">删除云端项目</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { createCloudProject, deleteCloudProject, listCloudProjects } from '@/api/cloud-project-api'
import { hasLocalWorkspace, runtimeMode } from '@/api/http'
import { downloadCloudProjectToLocal } from '@/services/sync-client'
import { useAuthStore } from '@/stores/auth'
import type { CloudProject } from '@/types/cloud'

const auth = useAuthStore()
const router = useRouter()
const projects = ref<CloudProject[]>([])
const loading = ref(false)
const name = ref('')
const description = ref('')
const agentHistorySync = ref(true)
const cloudWeb = runtimeMode === 'cloud'
onMounted(load)
async function load() {
  loading.value = true
  try { projects.value = await listCloudProjects(auth.workspace?.workspace_id) }
  finally { loading.value = false }
}
async function create() {
  if (!auth.workspace) return
  try {
    await ElMessageBox.confirm(
      `创建后项目元数据、论文、代码、追溯关系${agentHistorySync.value ? '及 Agent 工作记录' : ''}将存储在云端，并可同步到已绑定设备。此操作即为显式授权。`,
      '确认上云范围',
      { confirmButtonText: '确认创建云端项目', cancelButtonText: '取消', type: 'warning' },
    )
    const project = await createCloudProject({ workspace_id: auth.workspace.workspace_id, name: name.value.trim(), description: description.value.trim(), agent_history_sync: agentHistorySync.value })
    projects.value.unshift(project)
    name.value = ''; description.value = ''
  } catch (error) { if (error !== 'cancel') ElMessage.error('云端项目创建失败') }
}
function open(project: CloudProject) { void router.push(`/projects/${project.public_id}`) }
function handleRowDoubleClick(project: CloudProject) {
  if (cloudWeb) open(project)
  else void download(project)
}
async function download(project: CloudProject) {
  if (!auth.deviceId) return
  try {
    const projectId = await downloadCloudProjectToLocal(project, auth.deviceId)
    ElMessage.success('云端源数据已下载到本地工作台')
    void router.push(`/projects/${projectId}`)
  } catch {
    ElMessage.error('下载失败，已有本地数据不会被覆盖')
  }
}
async function removeCloud(project: CloudProject) {
  try {
    await ElMessageBox.confirm(
      '删除会影响 Web 和所有已绑定设备，并生成至少保留 30 天的 tombstone。解除本机绑定请在本地项目列表操作。',
      '删除云端项目',
      { type: 'error', confirmButtonText: '删除云端项目', cancelButtonText: '取消' },
    )
    await deleteCloudProject(project)
    projects.value = projects.value.filter((item) => item.public_id !== project.public_id)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除云端项目失败')
  }
}
</script>

<style scoped>.cloud-projects { width: min(1100px, 100%); margin: 24px auto; padding: 0 16px; }.heading,.create-row { display: flex; align-items: center; gap: 12px; }.create-row { margin: 16px 0; }.create-row .el-input { width: 280px; }</style>
