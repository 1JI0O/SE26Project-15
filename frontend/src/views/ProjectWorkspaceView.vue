<template>
  <div class="prototype-page">
    <!-- Header -->
    <section class="workspace-head">
      <div>
        <el-button text @click="$router.push('/')">返回项目入口</el-button>
        <div class="title-row">
          <h1>论文代码双向追溯工作台</h1>
          <el-tag effect="plain" type="warning">最终 UI 演示版</el-tag>
        </div>
        <p>
          输入论文 PDF 与代码 ZIP 后，左侧只读展示论文原文，右侧以 IDE 方式展示过滤后的代码仓库、
          可编辑代码文件，并基于项目代码生成张量流追踪图。
        </p>
      </div>
      <div class="head-meta">
        <span>Project {{ workspace.projectIdLabel }}</span>
        <strong>{{ workspace.projectName }}</strong>
      </div>
    </section>

    <!-- Hidden file inputs -->
    <input ref="paperInputRef" type="file" accept=".pdf,application/pdf" hidden @change="onPaperSelected" />
    <input ref="codeInputRef" type="file" accept=".zip,application/zip" hidden @change="onCodeSelected" />

    <!-- Import strip -->
    <ImportStrip
      :steps="importSteps"
      :loading-map="{ '01': paper.uploading.value, '02': code.uploading.value }"
      @action="handleImportAction"
    />

    <!-- Review toolbar -->
    <section class="review-toolbar">
      <div class="toolbar-group">
        <button
          v-for="mode in reviewModes"
          :key="mode"
          :class="['mode-button', { active: activeMode === mode }]"
          @click="activeMode = mode"
        >
          {{ mode }}
        </button>
      </div>
      <div class="toolbar-actions">
        <el-tag type="success" effect="plain">{{ trace.traceRows.value.length }} 条追溯候选</el-tag>
        <el-tag type="info" effect="plain">论文只读 / 代码可编辑</el-tag>
        <el-button type="primary">导出审阅报告</el-button>
      </div>
    </section>

    <!-- Main analysis canvas -->
    <section class="analysis-canvas">
      <PaperReader
        :filename="paper.paperFilename.value"
        :abstract="paper.paperAbstract.value"
        :page-numbers="paper.paperPageNumbers.value"
        :active-page="paper.activePaperPage.value"
        :active-content="paper.activePaperContent.value"
        :has-paper="paper.hasPaper.value"
        :loading="paper.loading.value"
        :error="paper.error.value"
        @update:active-page="(p) => (paper.activePaperPage.value = p)"
        @retry="paper.loadPaperPages"
      />

      <article class="code-panel">
        <header class="panel-title">
          <div>
            <h2>代码工作区</h2>
            <p>过滤 .gitignore 与 macOS 元数据后的完整仓库树，代码文件可直接编辑。</p>
          </div>
          <el-tag type="success" effect="plain">{{ code.codeFilename.value || '未上传代码' }}</el-tag>
        </header>

        <div class="code-workbench">
          <RepositoryTree
            :visible-tree="code.visibleCodeTree.value"
            :selected-path="code.selectedPath.value"
            :ignore-summary="code.ignoreSummary.value"
            :has-code="code.hasCode.value"
            :loading="code.loading.value"
            :error="code.error.value"
            :is-folder-expanded="code.isFolderExpanded"
            :chevron="code.folderChevron"
            :icon="fileIcon"
            :is-editable="isEditableFile"
            @node-click="code.handleTreeNodeClick"
            @retry="code.loadCodeTree"
          />

          <CodeEditor
            :file="code.selectedFile.value"
            :content="code.editorContent.value"
            :is-dirty="code.isEditorDirty.value"
            :saving="code.saving.value"
            @change="code.handleEditorInput"
            @save="code.saveEditorBuffer"
          />
        </div>
      </article>
    </section>

    <!-- Insight dock -->
    <InsightDock
      :tabs="insightTabs"
      :active-tab="activeInsight"
      @update:active-tab="(t) => (activeInsight = t)"
    >
      <!-- Trace matrix tab -->
      <div v-if="activeInsight === 'trace'" class="dock-grid">
        <TraceMatrix
          :rows="trace.traceRows.value"
          :loading="trace.loading.value"
          :error="trace.error.value"
        />
        <article class="assistant-panel">
          <h2>AI 审阅建议</h2>
          <p>
            BasicBlock.forward 与论文残差公式匹配度较高；建议人工确认 projection shortcut
            在 stride=2 时是否与论文描述一致。
          </p>
          <div class="suggestion-actions">
            <el-button type="primary">接受建议</el-button>
            <el-button>标记待确认</el-button>
          </div>
        </article>
      </div>

      <!-- Tensor flow tab -->
      <div v-else-if="activeInsight === 'flow'" class="tensor-flow-layout">
        <TensorFlowCanvas
          :nodes="tensorFlow.nodes.value"
          :edges="tensorFlow.edges.value"
          :edge-labels="tensorFlow.edgeLabels.value"
          :selected-node="tensorFlow.selectedNode.value"
          :edge-path="tensorFlow.edgePath"
          :loading="tensorFlow.loading.value"
          :error="tensorFlow.error.value"
          :degraded="tensorFlow.degraded.value"
          @node-click="onTensorNodeClick"
        />
        <TensorFlowInspector
          :node="tensorFlow.selectedNode.value"
          :current-file-path="code.selectedPath.value"
          @jump-to-code="onTensorJumpToCode"
        />
      </div>

      <!-- Conflict tab -->
      <ConflictPanel v-else-if="activeInsight === 'conflict'" :items="conflictItems" />

      <!-- Report tab -->
      <ReportPanel v-else :cards="reportCards" />
    </InsightDock>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

// Composables
import { useWorkspace } from '@/composables/useWorkspace'
import { usePaper } from '@/composables/usePaper'
import { useCode, isEditableFile, fileIcon } from '@/composables/useCode'
import { useTensorFlow, conflictItems, reportCards } from '@/composables/useTensorFlow'
import { useTrace } from '@/composables/useTrace'
import { useImport } from '@/composables/useImport'
import { useDesktop } from '@/composables/useDesktop'

// Feature components
import ImportStrip from '@/features/papers/ImportStrip.vue'
import PaperReader from '@/features/papers/PaperReader.vue'
import RepositoryTree from '@/features/repository/RepositoryTree.vue'
import CodeEditor from '@/features/repository/CodeEditor.vue'
import TensorFlowCanvas from '@/features/tensor-flow/TensorFlowCanvas.vue'
import TensorFlowInspector from '@/features/tensor-flow/TensorFlowInspector.vue'
import InsightDock from '@/features/tracing/InsightDock.vue'
import TraceMatrix from '@/features/tracing/TraceMatrix.vue'
import ConflictPanel from '@/features/tracing/ConflictPanel.vue'
import ReportPanel from '@/features/tracing/ReportPanel.vue'
import type { TensorFlowNode } from '@/composables/useTensorFlow'

// Initialize composables
const workspace = useWorkspace()
const paper = usePaper(() => workspace.projectId.value)
const code = useCode(() => workspace.projectId.value)
const tensorFlow = useTensorFlow()
const trace = useTrace(() => workspace.projectId.value)
const desktop = useDesktop()
const { importSteps } = useImport(
  () => paper.hasPaper.value,
  () => code.hasCode.value,
)

// Local state
const activeMode = ref('审阅模式')
const activeInsight = ref('trace')
const reviewModes = ['审阅模式', '标注模式', '冲突模式']

const insightTabs = [
  { key: 'trace', label: '追溯矩阵' },
  { key: 'flow', label: '张量流流程图' },
  { key: 'conflict', label: '魔改冲突分析' },
  { key: 'report', label: '报告与质量门禁' },
]

// File input refs
const paperInputRef = ref<HTMLInputElement | null>(null)
const codeInputRef = ref<HTMLInputElement | null>(null)

// Load workspace on mount
onMounted(async () => {
  if (!workspace.projectId.value || Number.isNaN(workspace.projectId.value)) return
  workspace.loadingWorkspace.value = true
  try {
    await workspace.loadProject()
    await Promise.allSettled([
      paper.loadPaperPages(),
      code.loadCodeTree(),
      trace.loadTraceRows(),
    ])
  } catch {
    ElMessage.error('加载项目工作台失败')
  } finally {
    workspace.loadingWorkspace.value = false
  }
})

// Import actions — use Tauri system dialog in desktop, fallback to HTML input in browser
async function handleImportAction(stepIndex: string): Promise<void> {
  if (stepIndex === '01') {
    if (desktop.isDesktop.value) {
      const file = await desktop.pickPdfFile()
      if (file) {
        const success = await paper.handleUpload(file)
        if (success) await trace.loadTraceRows()
      }
    } else {
      paperInputRef.value?.click()
    }
    return
  }
  if (stepIndex === '02') {
    if (desktop.isDesktop.value) {
      const file = await desktop.pickZipFile()
      if (file) {
        const success = await code.handleUpload(file)
        if (success) await trace.loadTraceRows()
      }
    } else {
      codeInputRef.value?.click()
    }
  }
}

async function onPaperSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const success = await paper.handleUpload(file)
  if (success) {
    await trace.loadTraceRows()
  }
}

async function onCodeSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const success = await code.handleUpload(file)
  if (success) {
    await trace.loadTraceRows()
  }
}

// Tensor flow handlers
function onTensorNodeClick(node: TensorFlowNode): void {
  tensorFlow.selectNode(node)
  void code.openCodeFile(node.sourcePath)
}

function onTensorJumpToCode(node: TensorFlowNode): void {
  void code.openCodeFile(node.sourcePath)
}
</script>

<style scoped>
.prototype-page {
  display: grid;
  gap: 18px;
  --workspace-panel-height: 1040px;
}

.workspace-head,
.review-toolbar {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.workspace-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 20px;
}

.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}

.workspace-head h1 {
  margin: 0;
  font-size: 26px;
}

.workspace-head p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.head-meta {
  display: grid;
  gap: 6px;
  min-width: 180px;
  padding: 12px;
  border-radius: 8px;
  background: #f3f7f6;
  text-align: right;
}

.head-meta span {
  color: #667789;
  font-size: 12px;
}

.review-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
}

.toolbar-group {
  display: inline-flex;
  gap: 6px;
  padding: 4px;
  border-radius: 8px;
  background: #eef3f2;
}

.mode-button {
  padding: 8px 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #536475;
  cursor: pointer;
  font: inherit;
}

.mode-button.active {
  background: #1f8f78;
  color: #ffffff;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.analysis-canvas {
  display: grid;
  grid-template-columns: minmax(460px, 0.92fr) minmax(560px, 1.08fr);
  gap: 16px;
  align-items: stretch;
}

.code-panel {
  display: flex;
  height: var(--workspace-panel-height);
  max-height: var(--workspace-panel-height);
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.panel-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.panel-title h2 {
  margin: 0;
}

.panel-title p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.code-workbench {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.dock-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.7fr);
  gap: 16px;
  padding: 16px;
}

.assistant-panel {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
}

.assistant-panel h2 {
  margin: 0;
}

.assistant-panel p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.suggestion-actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}

.tensor-flow-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(360px, 0.75fr);
  gap: 16px;
  padding: 16px;
}

@media (max-width: 1180px) {
  .analysis-canvas,
  .dock-grid,
  .tensor-flow-layout {
    grid-template-columns: 1fr;
  }

  .code-panel {
    height: auto;
    max-height: none;
    min-height: 840px;
  }
}

@media (max-width: 820px) {
  .workspace-head,
  .review-toolbar,
  .toolbar-actions,
  .panel-title {
    align-items: stretch;
    flex-direction: column;
  }

  .analysis-canvas,
  .code-workbench {
    grid-template-columns: 1fr;
  }

  .head-meta {
    text-align: left;
  }
}
</style>
