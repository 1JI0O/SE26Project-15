<template>
  <div class="project-page">
    <section class="project-panel">
      <header class="project-header">
        <div class="header-title">
          <el-icon><FolderOpened /></el-icon>
          <h1>工作区</h1>
          <span>{{ store.projects.length }} 个项目</span>
        </div>
        <div v-if="managing" class="batch-actions">
          <el-checkbox v-model="allSelected" :indeterminate="partlySelected">
            全选
          </el-checkbox>
          <span>已选择 {{ selectedIds.length }} 项</span>
          <el-button
            size="small"
            type="danger"
            :icon="Delete"
            :disabled="selectedIds.length === 0"
            :loading="store.deleting"
            @click="confirmDelete"
          >
            删除
          </el-button>
          <el-button size="small" @click="finishManaging">完成</el-button>
        </div>
        <el-button v-else size="small" :icon="EditPen" @click="managing = true">
          管理项目
        </el-button>
      </header>

      <el-form class="create-bar" :model="form" @submit.prevent="submit">
        <div class="create-label">
          <el-icon><Plus /></el-icon>
          <span>新建项目</span>
        </div>
        <el-input v-model="form.name" size="small" placeholder="项目名称" />
        <el-input
          v-model="form.description"
          class="description-input"
          size="small"
          placeholder="项目说明（可选）"
        />
        <el-button
          size="small"
          type="primary"
          native-type="submit"
          :loading="store.creating"
          :disabled="!form.name.trim()"
        >
          创建
        </el-button>
      </el-form>

      <div class="project-content">
        <el-skeleton v-if="store.loading" class="project-loading" :rows="5" animated />
        <el-empty v-else-if="store.projects.length === 0" description="暂无项目" />
        <template v-else>
          <div class="list-heading" aria-hidden="true">
            <span>项目</span>
            <span>说明</span>
            <span>最近更新</span>
            <span>操作</span>
          </div>
          <div class="project-list">
            <article
              v-for="project in store.projects"
              :key="project.id"
              class="project-row"
              :class="{ selected: selectedIds.includes(project.id) }"
              @dblclick="openProject(project.id)"
            >
              <div class="project-primary">
                <el-checkbox
                  v-if="managing"
                  v-model="selectedIds"
                  :value="project.id"
                  :aria-label="`选择项目 ${project.name}`"
                  @dblclick.stop
                />
                <el-icon class="project-icon"><Folder /></el-icon>
                <div>
                  <strong :title="project.name">{{ project.name }}</strong>
                  <small>#{{ project.id }} · {{ syncLabel(project.sync_mode) }}</small>
                </div>
              </div>
              <p :title="project.description || '未填写项目说明'">
                {{ project.description || '未填写项目说明' }}
              </p>
              <time :datetime="project.updated_at">{{ formatDate(project.updated_at) }}</time>
              <div class="row-actions">
                <template v-if="localCloudSyncAvailable">
                  <el-button v-if="project.sync_mode === 'local_only'" size="small" text @click.stop="openSyncDialog(project.id)">启用同步</el-button>
                  <el-button v-else-if="project.sync_mode === 'cloud_enabled'" size="small" text @click.stop="setSyncMode(project.id, 'cloud_paused')">暂停</el-button>
                  <el-button v-else-if="project.sync_mode === 'cloud_paused'" size="small" text @click.stop="setSyncMode(project.id, 'cloud_enabled')">继续</el-button>
                  <el-button v-if="['cloud_enabled', 'cloud_paused'].includes(project.sync_mode)" size="small" text type="danger" @click.stop="detach(project.id)">解除绑定</el-button>
                  <el-button v-else-if="project.sync_mode === 'cloud_detached'" size="small" text @click.stop="setSyncMode(project.id, 'local_only')">转为仅本地</el-button>
                </template>
                <el-button class="open-button" size="small" text type="primary" :icon="ArrowRight" aria-label="打开项目" @click="openProject(project.id)" />
              </div>
            </article>
          </div>
        </template>
      </div>
    </section>
    <el-dialog v-model="syncDialogOpen" title="启用项目云同步" width="480px">
      <p>将同步项目元数据、原始 PDF、代码版本、追溯关系和人工审阅结果。分析缓存、界面布局以及 MinerU/LLM 密钥不会上传。</p>
      <el-checkbox v-model="agentHistorySync">同步 Agent 对话、消息与记忆</el-checkbox>
      <template #footer>
        <el-button @click="syncDialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="sync.syncing" @click="enableSync">确认启用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ArrowRight, Delete, EditPen, Folder, FolderOpened, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { localCloudSyncAvailable } from '@/api/http'
import { useProjectStore } from '@/stores/project'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'

const router = useRouter()
const store = useProjectStore()
const auth = useAuthStore()
const sync = useSyncStore()
const managing = ref(false)
const selectedIds = ref<number[]>([])
const form = reactive({
  name: '',
  description: '',
})
const syncDialogOpen = ref(false)
const syncProjectId = ref<number | null>(null)
const agentHistorySync = ref(true)

const allSelected = computed({
  get: () =>
    store.projects.length > 0 && selectedIds.value.length === store.projects.length,
  set: (selected: boolean) => {
    selectedIds.value = selected ? store.projects.map((project) => project.id) : []
  },
})

const partlySelected = computed(
  () => selectedIds.value.length > 0 && selectedIds.value.length < store.projects.length,
)

onMounted(async () => {
  try {
    await store.fetchProjects()
  } catch (error) {
    console.error('Failed to load projects', error)
    ElMessage.error('项目列表加载失败，请确认本地后端已启动')
  }
})

async function submit() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  try {
    const project = await store.create({
      name: form.name.trim(),
      description: form.description.trim(),
    })
    form.name = ''
    form.description = ''
    await router.push({ name: 'workspace', params: { id: project.id } })
  } catch (error) {
    console.error('Failed to create project', error)
    ElMessage.error('项目创建失败，请检查后端连接后重试')
  }
}

function openProject(projectId: number) {
  void router.push({ name: 'workspace', params: { id: projectId } })
}

function syncLabel(mode: string) {
  return {
    local_only: '仅本地',
    cloud_enabled: '云同步',
    cloud_paused: '同步已暂停',
    cloud_detached: '已解除云端绑定',
  }[mode] ?? mode
}

function openSyncDialog(projectId: number) {
  if (!auth.authenticated || !auth.verified) {
    ElMessage.warning('请先登录后再启用项目云同步')
    void router.push('/login')
    return
  }
  syncProjectId.value = projectId
  agentHistorySync.value = true
  syncDialogOpen.value = true
}

async function enableSync() {
  if (syncProjectId.value === null) return
  try {
    await sync.enable(syncProjectId.value, agentHistorySync.value)
    syncDialogOpen.value = false
    await store.fetchProjects()
    ElMessage.success('项目云同步已启用')
  } catch {
    ElMessage.error('启用同步失败，本地项目未被删除或覆盖')
  }
}

async function setSyncMode(
  projectId: number,
  mode: 'cloud_enabled' | 'cloud_paused' | 'cloud_detached' | 'local_only',
) {
  try {
    await sync.setMode(projectId, mode)
    await store.fetchProjects()
  } catch {
    ElMessage.error('同步状态更新失败')
  }
}

async function detach(projectId: number) {
  try {
    await ElMessageBox.confirm(
      '仅解除当前设备与云端项目的绑定，本机项目将回到“仅本地”。云端项目和其他设备不受影响。',
      '解除云端绑定',
      { type: 'warning', confirmButtonText: '解除绑定', cancelButtonText: '取消' },
    )
    await setSyncMode(projectId, 'local_only')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('解除绑定失败')
  }
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function finishManaging() {
  managing.value = false
  selectedIds.value = []
}

async function confirmDelete() {
  const count = selectedIds.value.length
  if (!count) return
  try {
    await ElMessageBox.confirm(
      `将永久删除所选的 ${count} 个项目，以及对应的论文、代码和追溯记录。`,
      '删除项目',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
    const result = await store.deleteMany([...selectedIds.value])
    finishManaging()
    ElMessage.success(`已删除 ${result.deleted_ids.length} 个项目`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error('项目删除失败，请重试')
    }
  }
}
</script>

<style scoped>
.project-page {
  min-height: 100%;
  padding: 22px;
  background: #eef1f4;
}

.project-panel {
  width: min(1160px, 100%);
  min-height: 420px;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid #d8dee6;
  border-radius: 6px;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(36, 49, 61, 0.05);
}

.project-header,
.create-bar {
  display: flex;
  align-items: center;
  min-height: 42px;
  padding: 0 12px;
  border-bottom: 1px solid #d8dee6;
}

.project-header {
  justify-content: space-between;
  gap: 16px;
  background: #f7f8fa;
}

.header-title,
.create-label,
.batch-actions,
.project-primary {
  display: flex;
  align-items: center;
}

.header-title {
  min-width: 0;
  gap: 8px;
}

.header-title .el-icon {
  color: #1f8f78;
  font-size: 16px;
}

.header-title h1 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.header-title span,
.batch-actions span {
  color: #71808f;
  font-size: 12px;
}

.batch-actions {
  gap: 8px;
  white-space: nowrap;
}

.create-bar {
  display: grid;
  grid-template-columns: 100px minmax(180px, 0.8fr) minmax(240px, 1.4fr) auto;
  gap: 8px;
  background: #fbfcfd;
}

.create-label {
  gap: 6px;
  color: #4d5d6c;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.project-content {
  min-height: 334px;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.project-loading {
  padding: 18px;
}

.list-heading,
.project-row {
  display: grid;
  grid-template-columns: minmax(220px, 1.25fr) minmax(220px, 1.55fr) 150px 54px;
  align-items: center;
}

.list-heading {
  min-height: 30px;
  padding: 0 10px;
  border-bottom: 1px solid #e3e7ec;
  background: #f7f8fa;
  color: #71808f;
  font-size: 11px;
  font-weight: 600;
}

.list-heading span:last-child {
  text-align: center;
}

.project-row {
  min-height: 54px;
  padding: 0 10px;
  border-bottom: 1px solid #edf0f3;
  color: #344250;
  transition: background 0.12s ease;
}

.project-row:last-child {
  border-bottom: 0;
}

.project-row:hover,
.project-row.selected {
  background: #f1f8f6;
}

.project-row.selected {
  box-shadow: inset 2px 0 #1f8f78;
}

.project-primary {
  min-width: 0;
  gap: 8px;
  padding-right: 12px;
}

.project-primary > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.project-icon {
  flex: 0 0 auto;
  color: #1f8f78;
  font-size: 16px;
}

.project-primary strong,
.project-row p,
.project-row time {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-primary strong {
  font-size: 13px;
  font-weight: 600;
}

.project-primary small,
.project-row time {
  color: #82909d;
  font-size: 11px;
}

.project-row p {
  margin: 0;
  padding-right: 18px;
  color: #667789;
  font-size: 12px;
}

.open-button {
  justify-self: center;
}

@media (max-width: 780px) {
  .project-page {
    padding: 12px;
  }

  .create-bar {
    grid-template-columns: 92px 1fr auto;
  }

  .description-input {
    display: none;
  }

  .list-heading,
  .project-row {
    grid-template-columns: minmax(180px, 1fr) 130px 48px;
  }

  .list-heading span:nth-child(2),
  .project-row p {
    display: none;
  }
}

@media (max-width: 540px) {
  .project-header {
    align-items: flex-start;
    padding-top: 7px;
    padding-bottom: 7px;
  }

  .batch-actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .batch-actions > span {
    display: none;
  }

  .create-bar {
    grid-template-columns: 1fr auto;
  }

  .create-label {
    display: none;
  }

  .list-heading,
  .project-row {
    grid-template-columns: minmax(0, 1fr) 44px;
  }

  .list-heading span:nth-child(3),
  .project-row time {
    display: none;
  }
}
</style>
