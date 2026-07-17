<template>
  <div class="cloud-project">
    <el-page-header content="云端项目工作台" @back="router.push('/')" />
    <el-card v-if="project" class="project-card" shadow="never">
      <template #header>
        <div class="heading">
          <div><strong>{{ project.name }}</strong><p>{{ project.description || '未填写项目说明' }}</p></div>
          <div class="heading-actions">
            <el-switch
              :model-value="project.agent_history_sync"
              active-text="同步 Agent 历史"
              @change="toggleAgentHistory"
            />
            <el-tag type="success">云端 active · v{{ project.version }}</el-tag>
          </div>
        </div>
      </template>
      <el-alert
        title="本页直接写入 Cloud API；每次修改都会生成同步事件，已绑定的 Desktop 随后可拉取。"
        type="info"
        show-icon
        :closable="false"
      />
      <el-tabs v-model="activeTab" class="workspace-tabs">
        <el-tab-pane label="论文" name="papers">
          <section class="toolbar">
            <input type="file" accept="application/pdf,.pdf" @change="upload($event, 'paper_document')" />
            <span>PDF 以不可变版本保存；重新上传不会覆盖旧版本。</span>
          </section>
          <el-table :data="byType('paper_document')">
            <el-table-column label="文件"><template #default="scope">{{ scope.row.payload.filename }}</template></el-table-column>
            <el-table-column label="解析状态"><template #default="scope">{{ scope.row.payload.status ?? '已入队' }}</template></el-table-column>
            <el-table-column label="版本" prop="version" width="90" />
            <el-table-column label="操作" width="180"><template #default="scope">
              <el-button text @click="download(scope.row)">下载</el-button>
              <el-button text @click="showVersions(scope.row)">版本历史</el-button>
            </template></el-table-column>
          </el-table>
          <el-table v-if="byType('paper_analysis').length" :data="byType('paper_analysis')">
            <el-table-column label="解析结果"><template #default="scope">{{ scope.row.payload.processor_version }}</template></el-table-column>
            <el-table-column label="源文件哈希"><template #default="scope">{{ scope.row.payload.source_hash }}</template></el-table-column>
            <el-table-column label="操作" width="120"><template #default="scope"><el-button text @click="download(scope.row)">下载页面 JSON</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="代码" name="code">
          <section class="toolbar">
            <input type="file" accept="application/zip,.zip" @change="upload($event, 'code_repository')" />
            <span>代码 ZIP 上传后由云端 Worker 分析；编辑结果作为新版本。</span>
          </section>
          <el-table :data="byType('code_repository')">
            <el-table-column label="仓库"><template #default="scope">{{ scope.row.payload.filename }}</template></el-table-column>
            <el-table-column label="分析状态"><template #default="scope">{{ scope.row.payload.status ?? '已入队' }}</template></el-table-column>
            <el-table-column label="版本" prop="version" width="90" />
            <el-table-column label="操作" width="180"><template #default="scope">
              <el-button text @click="download(scope.row)">下载</el-button>
              <el-button text @click="showVersions(scope.row)">版本历史</el-button>
            </template></el-table-column>
          </el-table>
          <el-form class="code-edit-form" @submit.prevent="saveCodeEdit">
            <el-select v-model="codeEditRepository" placeholder="选择仓库">
              <el-option
                v-for="repository in byType('code_repository')"
                :key="repository.public_id"
                :label="String(repository.payload.filename ?? repository.public_id)"
                :value="repository.public_id"
              />
            </el-select>
            <el-input v-model="codeEditPath" placeholder="文件路径，例如 src/main.py" />
            <el-input v-model="codeEditContent" type="textarea" :rows="8" placeholder="编辑后的完整文本内容" />
            <el-button
              native-type="submit"
              type="primary"
              :disabled="!codeEditRepository || !codeEditPath || !codeEditContent"
            >保存为不可变代码版本</el-button>
          </el-form>
          <el-table :data="byType('code_edit')">
            <el-table-column label="编辑文件"><template #default="scope">{{ scope.row.payload.path }}</template></el-table-column>
            <el-table-column prop="version" label="实体版本" width="100" />
            <el-table-column label="操作" width="180"><template #default="scope">
              <el-button text @click="download(scope.row)">下载</el-button>
              <el-button text @click="showVersions(scope.row)">版本历史</el-button>
            </template></el-table-column>
          </el-table>
          <el-table v-if="byType('repository_analysis').length" :data="byType('repository_analysis')">
            <el-table-column label="分析器"><template #default="scope">{{ scope.row.payload.processor_version }}</template></el-table-column>
            <el-table-column label="源文件哈希"><template #default="scope">{{ scope.row.payload.source_hash }}</template></el-table-column>
            <el-table-column label="操作" width="120"><template #default="scope"><el-button text @click="download(scope.row)">下载代码树/分析 JSON</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="追溯关系" name="traces">
          <el-form class="trace-form" inline @submit.prevent="createTrace">
            <el-input v-model="tracePaper" placeholder="论文引用" />
            <el-input v-model="traceCode" placeholder="代码引用" />
            <el-button native-type="submit" type="primary" :disabled="!tracePaper || !traceCode">新建关系</el-button>
          </el-form>
          <el-table :data="byType('trace_link')">
            <el-table-column label="论文"><template #default="scope">{{ scope.row.payload.paper_ref }}</template></el-table-column>
            <el-table-column label="代码"><template #default="scope">{{ scope.row.payload.code_ref }}</template></el-table-column>
            <el-table-column label="人工决定"><template #default="scope"><el-tag>{{ scope.row.payload.status }}</el-tag></template></el-table-column>
            <el-table-column label="审阅" width="160"><template #default="scope">
              <el-button text type="success" @click="reviewTrace(scope.row, 'accepted')">接受</el-button>
              <el-button text type="danger" @click="reviewTrace(scope.row, 'rejected')">拒绝</el-button>
            </template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="Agent" name="agent">
          <el-alert
            v-if="!project.agent_history_sync"
            title="该项目已关闭 Agent 历史同步。Cloud Web 不会创建持久化 Agent 记录；Desktop 仍可仅本地运行。"
            type="warning"
            show-icon
          />
          <el-form class="agent-form" @submit.prevent="createAgentRecord">
            <el-input v-model="agentTitle" placeholder="会话标题" :disabled="!project.agent_history_sync" />
            <el-input v-model="agentMessage" type="textarea" :rows="4" placeholder="工作记录/消息" :disabled="!project.agent_history_sync" />
            <el-input v-model="agentMemory" placeholder="可选：同步为项目 Memory" :disabled="!project.agent_history_sync" />
            <el-button native-type="submit" type="primary" :disabled="!project.agent_history_sync || !agentTitle || !agentMessage">保存 Agent 工作记录</el-button>
          </el-form>
          <el-timeline>
            <el-timeline-item v-for="item in agentEntities" :key="item.public_id" :timestamp="item.updated_at">
              <strong>{{ item.entity_type }}</strong> · {{ item.payload.title ?? item.payload.role ?? item.payload.status ?? item.public_id }}
            </el-timeline-item>
          </el-timeline>
        </el-tab-pane>
        <el-tab-pane label="活动" name="activity">
          <el-table :data="entities">
            <el-table-column prop="entity_type" label="类型" />
            <el-table-column prop="public_id" label="UUID" />
            <el-table-column prop="version" label="版本" width="90" />
            <el-table-column prop="updated_at" label="更新时间" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-dialog v-model="versionsVisible" title="不可变文件版本" width="680px">
      <el-table :data="versions">
        <el-table-column prop="version_number" label="版本" width="80" />
        <el-table-column prop="source_hash" label="SHA-256" />
        <el-table-column label="状态" width="100"><template #default="scope">{{ scope.row.is_current ? '当前' : '保留' }}</template></el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="190" />
        <el-table-column label="操作" width="100"><template #default="scope"><el-button v-if="!scope.row.is_current" text @click="selectVersion(scope.row)">设为当前</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { cloudHttp } from '@/api/http'
import { CloudProjectGateway } from '@/services/project-gateway'
import type {
  ArtifactVersion,
  CloudDomainEntity,
  CloudEntityType,
  CloudProject,
} from '@/types/cloud'

const route = useRoute()
const router = useRouter()
const gateway = new CloudProjectGateway()
const project = ref<CloudProject | null>(null)
const entities = ref<CloudDomainEntity[]>([])
const activeTab = ref('papers')
const tracePaper = ref('')
const traceCode = ref('')
const agentTitle = ref('')
const agentMessage = ref('')
const agentMemory = ref('')
const codeEditRepository = ref('')
const codeEditPath = ref('')
const codeEditContent = ref('')
const versions = ref<ArtifactVersion[]>([])
const versionsVisible = ref(false)
const versionEntity = ref<CloudDomainEntity | null>(null)
const projectId = computed(() => String(route.params.id))
const agentEntities = computed(() => entities.value.filter((item) => item.entity_type.startsWith('agent_')))

function byType(type: string) {
  return entities.value.filter((item) => item.entity_type === type)
}

async function load() {
  project.value = await gateway.getProject(projectId.value) as CloudProject
  await cloudHttp.patch(`/projects/${projectId.value}/device-sync`, { sync_mode: 'cloud_enabled' })
  entities.value = await gateway.listEntities(projectId.value)
}

async function upload(event: Event, entityType: 'paper_document' | 'code_repository') {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !project.value) return
  try {
    const blobId = await gateway.uploadSource(project.value, file)
    await gateway.createEntity(projectId.value, entityType, {
      filename: file.name,
      blob_id: blobId,
      status: 'queued',
    })
    ElMessage.success('文件已上传并进入云端处理队列')
    await load()
  } catch {
    ElMessage.error('上传失败；已存在的版本不会被覆盖')
  } finally {
    input.value = ''
  }
}

async function download(entity: CloudDomainEntity) {
  const blobId = entity.payload.blob_id ?? entity.payload.result_blob_id
  if (typeof blobId !== 'string') return
  const response = await cloudHttp.get<Blob>(`/blobs/${blobId}/download`, { responseType: 'blob' })
  const href = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = String(entity.payload.filename ?? 'download.bin')
  anchor.click()
  URL.revokeObjectURL(href)
}

async function showVersions(entity: CloudDomainEntity) {
  versionEntity.value = entity
  versions.value = await gateway.listVersions(projectId.value, entity)
  versionsVisible.value = true
}

async function selectVersion(version: ArtifactVersion) {
  if (!versionEntity.value) return
  await cloudHttp.post(
    `/projects/${projectId.value}/artifacts/${versionEntity.value.entity_type}/`
      + `${versionEntity.value.public_id}/versions/${version.version_id}/select`,
    undefined,
    { params: { base_version: versionEntity.value.version } },
  )
  versionsVisible.value = false
  await load()
}

async function createTrace() {
  await gateway.createEntity(projectId.value, 'trace_link', {
    paper_ref: tracePaper.value,
    code_ref: traceCode.value,
    relation_type: 'supports',
    status: 'pending',
    rationale: '',
  })
  tracePaper.value = ''
  traceCode.value = ''
  await load()
}

async function saveCodeEdit() {
  if (!project.value) return
  const pathParts = codeEditPath.value.split('/').filter(Boolean)
  const filename = pathParts[pathParts.length - 1] ?? 'edit.txt'
  try {
    const blobId = await gateway.uploadSource(
      project.value,
      new File([codeEditContent.value], filename, { type: 'text/plain' }),
    )
    await gateway.createEntity(projectId.value, 'code_edit', {
      repository_public_id: codeEditRepository.value,
      path: codeEditPath.value,
      filename,
      blob_id: blobId,
    })
    codeEditPath.value = ''
    codeEditContent.value = ''
    ElMessage.success('代码编辑已保存为不可变版本')
    await load()
  } catch {
    ElMessage.error('代码版本保存失败')
  }
}

async function reviewTrace(entity: CloudDomainEntity, status: 'accepted' | 'rejected') {
  await gateway.updateEntity(projectId.value, entity, { ...entity.payload, status })
  await load()
}

async function createAgentRecord() {
  if (!project.value) return
  const conversation = await gateway.createEntity(projectId.value, 'agent_conversation', {
    title: agentTitle.value,
    status: 'active',
    summary: '',
  })
  const messagePayload: Record<string, unknown> = {
    conversation_public_id: conversation.public_id,
    role: 'user',
    content: agentMessage.value,
  }
  if (new TextEncoder().encode(agentMessage.value).byteLength > 32 * 1024) {
    messagePayload.blob_id = await gateway.uploadSource(
      project.value,
      new File([agentMessage.value], `${crypto.randomUUID()}.txt`, { type: 'text/plain' }),
    )
    messagePayload.content = ''
  }
  await gateway.createEntity(projectId.value, 'agent_message', messagePayload)
  const run = await gateway.createEntity(projectId.value, 'agent_run', {
    conversation_public_id: conversation.public_id,
    status: 'completed',
    step_count: 1,
  })
  await gateway.createEntity(projectId.value, 'agent_run_event', {
    conversation_public_id: conversation.public_id,
    run_public_id: run.public_id,
    event_type: 'work_record.saved',
    sequence: 1,
    payload: { summary: '用户在 Cloud Web 保存 Agent 工作记录' },
  })
  if (agentMemory.value.trim()) {
    await gateway.createEntity(projectId.value, 'agent_memory', {
      conversation_public_id: conversation.public_id,
      kind: 'project_note',
      scope: 'project',
      content: agentMemory.value.trim(),
      importance: 0.5,
    })
  }
  agentTitle.value = ''
  agentMessage.value = ''
  agentMemory.value = ''
  await load()
}

async function toggleAgentHistory(value: string | number | boolean) {
  if (!project.value) return
  await cloudHttp.patch(`/projects/${project.value.public_id}`, {
    base_version: project.value.version,
    agent_history_sync: Boolean(value),
  })
  await load()
}

onMounted(async () => {
  try { await load() } catch { ElMessage.error('无法加载云端工作台') }
})
</script>

<style scoped>
.cloud-project { width: min(1200px, 100%); margin: 24px auto; padding: 0 16px; }
.project-card { margin-top: 18px; }
.heading, .heading-actions, .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.heading p { margin: 6px 0 0; color: var(--el-text-color-secondary); font-weight: normal; }
.workspace-tabs { margin-top: 18px; }
.toolbar, .trace-form, .agent-form { margin-bottom: 18px; }
.toolbar span { color: var(--el-text-color-secondary); font-size: 13px; }
.trace-form .el-input { width: 280px; }
.agent-form { display: grid; gap: 12px; max-width: 760px; }
.code-edit-form { display: grid; gap: 12px; max-width: 820px; margin: 24px 0; }
</style>
