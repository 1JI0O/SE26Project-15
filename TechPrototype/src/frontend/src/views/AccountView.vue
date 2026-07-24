<template>
  <div class="account-page">
    <el-card shadow="never">
      <template #header><strong>账号与设备</strong></template>
      <el-descriptions v-if="auth.user" :column="1" border>
        <el-descriptions-item label="邮箱">{{ auth.user.email }}</el-descriptions-item>
        <el-descriptions-item label="验证状态">{{ auth.user.email_verified ? '已验证' : '未验证' }}</el-descriptions-item>
        <el-descriptions-item label="默认工作区">{{ auth.workspace?.name ?? '-' }}</el-descriptions-item>
      </el-descriptions>
      <h3>Workspace</h3>
      <div class="workspace-switcher">
        <el-select :model-value="auth.workspace?.workspace_id" @change="switchWorkspace">
          <el-option v-for="item in workspaces" :key="item.workspace_id" :label="`${item.name} (${item.role})`" :value="item.workspace_id" />
        </el-select>
        <el-input v-model="newWorkspaceName" placeholder="新 Workspace 名称" />
        <el-button type="primary" @click="addWorkspace">创建</el-button>
      </div>
      <h3>登录设备</h3>
      <el-table :data="devices">
        <el-table-column prop="name" label="设备" />
        <el-table-column prop="platform" label="平台" width="120" />
        <el-table-column prop="last_seen_at" label="最近活动" width="190" />
        <el-table-column label="操作" width="100">
          <template #default="scope">
            <el-button v-if="!scope.row.current" text type="danger" @click="remove(scope.row.device_id)">撤销</el-button>
            <el-tag v-else size="small">当前</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-card v-if="auth.workspace" class="members" shadow="never">
      <template #header><strong>Workspace 成员</strong></template>
      <div v-if="auth.workspace.role === 'owner'" class="member-add">
        <el-input v-model="memberEmail" placeholder="已注册用户邮箱" />
        <el-select v-model="memberRole"><el-option label="编辑者" value="editor" /><el-option label="只读" value="viewer" /></el-select>
        <el-button type="primary" @click="addMember">添加</el-button>
      </div>
      <el-table :data="members">
        <el-table-column prop="email" label="邮箱" />
        <el-table-column prop="display_name" label="名称" />
        <el-table-column label="角色" width="150"><template #default="scope">
          <el-select v-if="auth.workspace?.role === 'owner' && scope.row.role !== 'owner'" :model-value="scope.row.role" @change="changeRole(scope.row, $event)">
            <el-option label="编辑者" value="editor" /><el-option label="只读" value="viewer" />
          </el-select><el-tag v-else>{{ scope.row.role }}</el-tag>
        </template></el-table-column>
        <el-table-column v-if="auth.workspace.role === 'owner'" label="操作" width="90"><template #default="scope"><el-button v-if="scope.row.role !== 'owner'" text type="danger" @click="removeMember(scope.row.user_id)">移除</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { addWorkspaceMember, createWorkspace, listDevices, listWorkspaceMembers, listWorkspaces, removeWorkspaceMember, revokeDevice, updateWorkspaceMember, type WorkspaceMember } from '@/api/auth-api'
import { useAuthStore } from '@/stores/auth'
import type { CloudWorkspace } from '@/types/cloud'

const auth = useAuthStore()
const devices = ref<Awaited<ReturnType<typeof listDevices>>>([])
const members = ref<WorkspaceMember[]>([])
const memberEmail = ref('')
const memberRole = ref<'editor' | 'viewer'>('editor')
const workspaces = ref<CloudWorkspace[]>([])
const newWorkspaceName = ref('')
onMounted(async () => {
  devices.value = await listDevices()
  workspaces.value = await listWorkspaces()
  if (auth.workspace) members.value = await listWorkspaceMembers(auth.workspace.workspace_id)
})
async function switchWorkspace(workspaceId: string) {
  const workspace = workspaces.value.find((item) => item.workspace_id === workspaceId)
  if (!workspace) return
  auth.selectWorkspace(workspace)
  members.value = await listWorkspaceMembers(workspaceId)
}
async function addWorkspace() {
  if (!newWorkspaceName.value.trim()) return
  const workspace = await createWorkspace(newWorkspaceName.value.trim())
  workspaces.value.push(workspace)
  newWorkspaceName.value = ''
  await switchWorkspace(workspace.workspace_id)
}
async function remove(deviceId: string) {
  await revokeDevice(deviceId)
  devices.value = devices.value.filter((item) => item.device_id !== deviceId)
  ElMessage.success('设备会话已撤销')
}
async function addMember() {
  if (!auth.workspace || !memberEmail.value.trim()) return
  const member = await addWorkspaceMember(auth.workspace.workspace_id, memberEmail.value.trim(), memberRole.value)
  members.value.push(member); memberEmail.value = ''; ElMessage.success('成员已添加')
}
async function changeRole(member: WorkspaceMember, role: 'editor' | 'viewer') {
  if (!auth.workspace) return
  const updated = await updateWorkspaceMember(auth.workspace.workspace_id, member.user_id, role)
  members.value = members.value.map((item) => item.user_id === updated.user_id ? updated : item)
}
async function removeMember(userId: string) {
  if (!auth.workspace) return
  await removeWorkspaceMember(auth.workspace.workspace_id, userId)
  members.value = members.value.filter((item) => item.user_id !== userId)
}
</script>

<style scoped>.account-page { width: min(900px, 100%); margin: 24px auto; padding: 0 16px; } h3 { margin-top: 24px; }.members { margin-top: 16px; }.member-add,.workspace-switcher { display: flex; gap: 10px; margin-bottom: 16px; }.member-add .el-input,.workspace-switcher .el-input { flex: 1; }.member-add .el-select,.workspace-switcher .el-select { width: 220px; }</style>
