<template>
  <div class="ide-workbench">
    <input ref="paperInputRef" type="file" accept=".pdf,application/pdf" hidden @change="onPaperSelected" />
    <input ref="codeInputRef" type="file" accept=".zip,application/zip" hidden @change="onCodeSelected" />

    <header class="command-bar">
      <div class="project-breadcrumb">
        <el-tooltip content="返回项目列表" placement="bottom">
          <el-button text :icon="Back" aria-label="返回项目列表" @click="$router.push('/')" />
        </el-tooltip>
        <span class="project-name">{{ workspace.projectName.value }}</span>
        <span class="breadcrumb-separator">/</span>
        <span>论文代码工作台</span>
        <el-tag v-if="desktop.isDesktop.value" size="small" type="success" effect="plain">
          Desktop
        </el-tag>
      </div>

      <div class="mode-switch" aria-label="工作模式">
        <button
          v-for="mode in reviewModes"
          :key="mode"
          :class="{ active: activeMode === mode }"
          @click="activeMode = mode"
        >
          {{ mode }}
        </button>
      </div>

      <div class="command-actions">
        <el-button size="small" aria-label="交换论文与代码视图" @click="paperFirst = !paperFirst">
          <span>交换视图</span>
        </el-button>
        <el-button
          size="small"
          :icon="DocumentAdd"
          :loading="paper.uploading.value"
          @click="handleImportAction('01')"
        >
          <span>导入论文</span>
        </el-button>
        <el-button
          size="small"
          :icon="UploadFilled"
          :loading="code.uploading.value"
          @click="handleImportAction('02')"
        >
          <span>导入代码</span>
        </el-button>
        <el-button
          size="small"
          type="primary"
          :icon="MagicStick"
          :loading="trace.generating.value"
          @click="openTraceAndGenerate"
        >
          <span>生成追溯</span>
        </el-button>
        <el-button size="small" @click="openArtifactVersions">版本历史</el-button>
        <!-- 需求 3.1: sync a synced project from inside the workbench -->
        <template v-if="cloudSyncEnabled && workspace.syncMode.value === 'cloud_enabled'">
          <el-tag size="small" :type="workspaceStatus.type" effect="plain" round>
            {{ workspaceStatus.label }}
          </el-tag>
          <el-button
            size="small"
            :icon="Refresh"
            :loading="sync.syncing"
            @click="syncWorkspace"
          >
            <span>同步</span>
          </el-button>
        </template>
      </div>
    </header>

    <div ref="ideBodyRef" class="ide-body">
      <nav class="activity-bar" aria-label="工作台工具">
        <el-tooltip content="资源管理器" placement="right">
          <button
            :class="['activity-button', { active: explorerOpen }]"
            aria-label="资源管理器"
            @click="explorerOpen = !explorerOpen"
          >
            <el-icon :size="21"><Files /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="双向追溯" placement="right">
          <button
            :class="['activity-button', { active: bottomPanelOpen && activeBottomPanel === 'trace' }]"
            aria-label="双向追溯"
            @click="openBottomPanel('trace')"
          >
            <el-icon :size="21"><Connection /></el-icon>
            <span v-if="trace.traceRows.value.length" class="activity-badge">
              {{ Math.min(trace.traceRows.value.length, 99) }}
            </span>
          </button>
        </el-tooltip>
        <el-tooltip content="张量流图" placement="right">
          <button
            :class="['activity-button', { active: bottomPanelOpen && activeBottomPanel === 'flow' }]"
            aria-label="张量流图"
            @click="openBottomPanel('flow')"
          >
            <el-icon :size="21"><Share /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="魔改冲突分析" placement="right">
          <button
            :class="['activity-button', { active: bottomPanelOpen && activeBottomPanel === 'conflict' }]"
            aria-label="魔改冲突分析"
            @click="openBottomPanel('conflict')"
          >
            <el-icon :size="21"><Warning /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip content="报告与质量" placement="right">
          <button
            :class="['activity-button', { active: bottomPanelOpen && activeBottomPanel === 'report' }]"
            aria-label="报告与质量"
            @click="openBottomPanel('report')"
          >
            <el-icon :size="21"><DataAnalysis /></el-icon>
          </button>
        </el-tooltip>

        <div class="activity-spacer" />

        <el-tooltip content="论文与代码 Agent" placement="right">
          <button
            :class="['activity-button', { active: agentOpen }]"
            aria-label="论文与代码 Agent"
            @click="agentOpen = !agentOpen"
          >
            <el-icon :size="21"><ChatLineRound /></el-icon>
          </button>
        </el-tooltip>
      </nav>

      <aside
        v-if="explorerOpen"
        class="explorer-sidebar"
        :style="{ width: `${explorerWidth}px`, flexBasis: `${explorerWidth}px` }"
      >
        <header class="sidebar-header">
          <span>资源管理器</span>
          <el-button text :icon="Close" aria-label="关闭资源管理器" @click="explorerOpen = false" />
        </header>
        <nav class="explorer-tabs" aria-label="资源管理器视图">
          <button
            :class="{ active: activeExplorerView === 'files' }"
            @click="activeExplorerView = 'files'"
          >
            文件
          </button>
          <button
            :class="{ active: activeExplorerView === 'outline' }"
            @click="activeExplorerView = 'outline'"
          >
            论文目录
          </button>
        </nav>

        <div v-show="activeExplorerView === 'files'" class="explorer-content file-explorer-content">
          <section class="project-overview">
            <div class="project-root-row">
              <el-icon><FolderOpened /></el-icon>
              <strong :title="workspace.projectName.value">{{ workspace.projectName.value }}</strong>
            </div>
            <div class="import-state-list">
              <button
                v-for="step in importSteps"
                :key="step.index"
                :class="['import-state', { ready: step.tagType === 'success' }]"
                :disabled="!step.action"
                @click="step.action && handleImportAction(step.index)"
              >
                <span>{{ step.index }}</span>
                <div>
                  <strong>{{ step.title }}</strong>
                  <small>{{ step.status }}</small>
                </div>
              </button>
            </div>
          </section>

          <section class="github-import">
            <el-input
              v-model="githubUrl"
              size="small"
              placeholder="GitHub 仓库 URL"
              clearable
              @keyup.enter="onGitHubImport"
            />
            <el-tooltip content="从 GitHub 导入公开仓库" placement="bottom">
              <el-button
                size="small"
                :icon="Download"
                :loading="code.importingGithub.value"
                :disabled="!githubUrl.trim()"
                aria-label="从 GitHub 导入"
                @click="onGitHubImport"
              />
            </el-tooltip>
          </section>

          <div v-if="code.analysisSummary.value" class="repository-stats">
            <span>{{ code.analysisSummary.value.file_count }} 文件</span>
            <span>{{ code.analysisSummary.value.symbol_count }} 符号</span>
            <span>{{ code.analysisSummary.value.call_count }} 调用</span>
          </div>

          <div class="tree-container">
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
          </div>
        </div>

        <div v-show="activeExplorerView === 'outline'" class="explorer-content outline-content">
          <PaperOutlineTree
            :sections="paper.paperSections.value"
            :active-section-id="paper.activeSectionId.value"
            @select="onOutlineSelect"
          />
        </div>
      </aside>

      <div
        v-if="explorerOpen"
        class="explorer-resize-handle"
        role="separator"
        aria-label="调整文件树宽度"
        aria-orientation="vertical"
        @pointerdown="startResize('explorer', $event)"
      />

      <main ref="workAreaRef" class="work-area">
        <section
          ref="editorGridRef"
          class="editor-grid"
          :style="{ '--left-pane-width': `${editorLeftPercent}%` }"
        >
          <article
            class="editor-pane paper-pane"
            :style="{ order: paperFirst ? 0 : 2 }"
            @dragover.prevent
            @drop="dropPane('paper')"
          >
            <div
              class="pane-tab-strip draggable-tab"
              draggable="true"
              title="拖动到另一侧可交换视图"
              @dragstart="startPaneDrag('paper', $event)"
              @dragend="draggedPane = null"
            >
              <span class="pane-tab active">
                <el-icon><Document /></el-icon>
                {{ paper.paperFilename.value || '论文.pdf' }}
              </span>
              <span class="pane-meta">
                只读 ·
                {{
                  paper.parserName.value ||
                  (['queued', 'running'].includes(paper.parseStatus.value) ? '解析中…' : '等待解析')
                }}
              </span>
            </div>
            <PaperReader
              ref="paperReaderRef"
              :markdown="paper.paperDocument.value?.markdown || ''"
              :asset-base-url="paper.paperDocument.value?.asset_base_url || ''"
              :active-section-id="paper.activeSectionId.value"
              :has-paper="paper.hasPaper.value"
              :loading="paper.loading.value"
              :error="paper.error.value"
              :source="paper.paperDocument.value?.source || ''"
              :parse-status="paper.parseStatus.value"
              :blocks="paper.paperDocument.value?.blocks || []"
              :trace-targets="paperMarks"
              :active-target-ids="traceIndex.activePaperTargetIds.value"
              :reveal-active="traceIndex.activeSide.value === 'code'"
              @select-section="paper.selectSection"
              @retry="paper.loadPaperPages"
              @trace-hover="traceIndex.hoverPaper"
              @trace-leave="traceIndex.clearHover"
              @trace-pin="(id: string) => traceIndex.pin('paper', id)"
            />
          </article>

          <div
            class="editor-resize-handle"
            :style="{ order: 1 }"
            role="separator"
            aria-label="调整论文与代码视图宽度"
            aria-orientation="vertical"
            @pointerdown="startResize('editor', $event)"
          />

          <article
            class="editor-pane code-pane"
            :style="{ order: paperFirst ? 2 : 0 }"
            @dragover.prevent
            @drop="dropPane('code')"
          >
            <div
              class="pane-tab-strip draggable-tab"
              draggable="true"
              title="拖动到另一侧可交换视图"
              @dragstart="startPaneDrag('code', $event)"
              @dragend="draggedPane = null"
            >
              <span class="pane-tab active">
                <el-icon><Tickets /></el-icon>
                {{ code.selectedPath.value || '选择代码文件' }}
              </span>
              <span v-if="code.isEditorDirty.value" class="dirty-indicator">未保存</span>
            </div>
            <CodeEditor
              ref="codeEditorRef"
              :file="code.selectedFile.value"
              :content="code.editorContent.value"
              :is-dirty="code.isEditorDirty.value"
              :saving="code.saving.value"
              :trace-targets="codeTargetList"
              :active-target-ids="traceIndex.activeCodeTargetIds.value"
              :reveal-active="traceIndex.activeSide.value === 'paper'"
              @change="code.handleEditorInput"
              @save="onSaveCode"
              @trace-hover="traceIndex.hoverCode"
              @trace-leave="traceIndex.clearHover"
              @trace-pin="(id: string) => traceIndex.pin('code', id)"
            />
          </article>
        </section>

        <section
          v-if="bottomPanelOpen"
          :class="['bottom-panel', { maximized: bottomPanelMaximized }]"
          :style="bottomPanelMaximized ? undefined : { height: `${bottomPanelHeight}px` }"
        >
          <div
            class="bottom-resize-handle"
            role="separator"
            aria-label="调整底部面板高度"
            aria-orientation="horizontal"
            @pointerdown="startResize('bottom', $event)"
          />
          <header class="bottom-panel-header">
            <nav class="bottom-tabs" aria-label="底部工具面板">
              <button
                v-for="tab in bottomTabs"
                :key="tab.key"
                :class="{ active: activeBottomPanel === tab.key }"
                @click="openBottomPanel(tab.key)"
              >
                {{ tab.label }}
                <span v-if="tab.key === 'trace'">{{ trace.traceRows.value.length }}</span>
              </button>
            </nav>
            <div class="panel-controls">
              <el-tooltip :content="bottomPanelMaximized ? '还原面板' : '最大化面板'" placement="top">
                <el-button
                  text
                  :icon="bottomPanelMaximized ? ArrowDown : ArrowUp"
                  :aria-label="bottomPanelMaximized ? '还原面板' : '最大化面板'"
                  @click="bottomPanelMaximized = !bottomPanelMaximized"
                />
              </el-tooltip>
              <el-tooltip content="关闭面板" placement="top">
                <el-button text :icon="Close" aria-label="关闭底部面板" @click="bottomPanelOpen = false" />
              </el-tooltip>
            </div>
          </header>

          <div class="bottom-panel-content">
            <div v-if="activeBottomPanel === 'trace'" class="trace-panel-layout">
              <TraceMatrix
                :rows="trace.traceRows.value"
                :loading="trace.loading.value"
                :generating="trace.generating.value"
                :error="trace.error.value"
                :mode="trace.mode.value"
                :degraded="trace.degraded.value"
                :has-generated="hasGeneratedTrace"
                @suggest="generateAgentAnalysis(hasGeneratedTrace)"
                @review="trace.reviewTrace"
                @select-row="onTraceRowSelect"
                @open-paper="jumpToTracePaper"
                @open-code="jumpToTraceCode"
                @hover-row="hoverTraceRow"
                @leave-row="traceIndex.clearHover"
              />
              <aside class="trace-summary">
                <strong>Agent 分析</strong>
                <span v-if="trace.mode.value">{{ trace.mode.value }}</span>
                <span v-else>Agent 自主读取论文与代码证据</span>

                <template v-if="trace.generating.value">
                  <div class="agent-activity">
                    <el-icon class="spin"><Loading /></el-icon>
                    <span class="agent-activity-text">{{ trace.analysisActivity.value || '启动中…' }}</span>
                  </div>
                  <el-progress
                    v-if="trace.analysisBudget.value"
                    :percentage="Math.min(100, Math.round((trace.analysisStep.value / trace.analysisBudget.value) * 100))"
                    :format="() => `步骤 ${trace.analysisStep.value}/${trace.analysisBudget.value}`"
                    :stroke-width="10"
                  />
                  <ul v-if="trace.analysisLog.value.length" class="agent-log">
                    <li v-for="(entry, i) in trace.analysisLog.value.slice().reverse()" :key="i">
                      {{ entry }}
                    </li>
                  </ul>
                </template>
                <p v-else-if="trace.analysisProgress.value">{{ trace.analysisProgress.value }}</p>
                <p v-if="trace.degradedReason.value" class="agent-degraded">
                  {{ trace.degradedReason.value }}
                </p>
                <el-button
                  size="small"
                  type="primary"
                  :loading="trace.generating.value"
                  @click="generateAgentAnalysis(hasGeneratedTrace)"
                >
                  {{
                    trace.generating.value
                      ? 'Agent 追溯中…'
                      : hasGeneratedTrace
                        ? '重新生成'
                        : '生成追溯'
                  }}
                </el-button>
              </aside>
            </div>

            <div v-else-if="activeBottomPanel === 'flow'" class="tensor-flow-layout">
              <TensorFlowCanvas
                :nodes="tensorFlow.nodes.value"
                :edges="tensorFlow.edges.value"
                :edge-labels="tensorFlow.edgeLabels.value"
                :selected-node="tensorFlow.selectedNode.value"
                :edge-path="tensorFlow.edgePath"
                :loading="tensorFlow.loading.value"
                :error="tensorFlow.error.value"
                :degraded="tensorFlow.degraded.value"
                :analysis-status="tensorFlow.analysisStatus.value"
                :analysis-stale="tensorFlow.analysisStale.value"
                :current-view="tensorFlow.currentView.value"
                :root-symbol="tensorFlow.rootSymbol.value"
                :root-label="tensorFlow.rootLabel.value"
                :available-roots="tensorFlow.availableRoots.value"
                :can-go-back="tensorFlow.navigationStack.value.length > 0"
                @node-click="onTensorNodeClick"
                @expand-node="tensorFlow.expandNode"
                @view-change="tensorFlow.setView"
                @root-change="tensorFlow.selectRoot"
                @back="tensorFlow.navigateBack"
              />
              <TensorFlowInspector
                :node="tensorFlow.selectedNode.value"
                :current-file-path="code.selectedPath.value"
                @jump-to-code="onTensorJumpToCode"
                @expand-node="tensorFlow.expandNode"
              />
            </div>

            <ConflictPanel
              v-else-if="activeBottomPanel === 'conflict'"
              :items="insights.conflictItems.value"
            />

            <div v-else-if="activeBottomPanel === 'report'" class="report-panel-wrap">
              <div class="report-actions">
                <span>质量指标与报告接口状态</span>
                <el-tooltip content="报告导出接口已预留，当前迭代不生成文件">
                  <span><el-button size="small" :icon="Download" disabled>导出报告</el-button></span>
                </el-tooltip>
              </div>
              <ReportPanel :cards="insights.reportCards.value" />
            </div>
          </div>
        </section>
      </main>

      <div
        v-if="agentOpen"
        class="agent-resize-handle"
        :style="{ '--agent-width': `${agentWidth}px` }"
        role="separator"
        aria-label="调整 Agent 宽度"
        aria-orientation="vertical"
        @pointerdown="startResize('agent', $event)"
      />

      <aside
        v-if="agentOpen"
        class="agent-sidebar"
        :style="{ width: `${agentWidth}px`, flexBasis: `${agentWidth}px` }"
      >
        <header class="sidebar-header">
          <span>Agent</span>
          <el-button text :icon="Close" aria-label="关闭 Agent" @click="agentOpen = false" />
        </header>
        <div class="agent-content">
          <AgentPanel
            :project-id="workspace.projectId.value"
            :paper-ref="trace.traceRows.value[0]?.paper"
            :code-ref="code.selectedFile.value?.symbol || code.selectedPath.value"
            :graph-node-id="tensorFlow.selectedNode.value?.id"
            :file-path="code.selectedPath.value"
            :trace-id="selectedTraceRow?.id"
            :graph-root-symbol="tensorFlow.rootSymbol.value || undefined"
            @executed="reloadAfterAgentAction"
            @ui-action="handleAgentUiAction"
          />
        </div>
      </aside>
    </div>

    <footer class="status-bar">
      <span><el-icon><Connection /></el-icon> {{ trace.traceRows.value.length }} 条追溯</span>
      <span>{{ paper.hasPaper.value ? '论文已解析' : '等待论文' }}</span>
      <el-tooltip
        content="对上传代码做静态分析：构建文件树、解析符号/调用、抽取张量流图，供追溯 Agent 导航。大仓库走后台任务，较慢。"
        placement="top"
      >
        <span>{{ repositoryStatusLabel }}</span>
      </el-tooltip>
      <span class="status-spacer" />
      <span>{{ code.selectedFile.value?.symbol || '无活动符号' }}</span>
      <span>Project {{ workspace.projectIdLabel }}</span>
    </footer>

    <EvidenceDrawer
      :visible="evidenceDrawerVisible"
      :row="selectedTraceRow"
      @close="evidenceDrawerVisible = false"
      @confirm="onEvidenceConfirm"
      @reject="onEvidenceReject"
      @open-paper="jumpToTracePaper"
      @open-code="jumpToTraceCode"
    />

    <!-- Bidirectional hover/pin popover: counterpart targets ranked by relevance. -->
    <div v-if="traceCounterparts.length" class="trace-hover-popover">
      <header class="trace-hover-head">
        <span>{{ traceIndex.activeSide.value === 'paper' ? '对应代码片段' : '对应论文片段' }}</span>
        <span class="trace-hover-count">
          {{ traceCounterparts.length }} 条 · 按相关度
          <button
            v-if="traceIndex.pinned.value"
            class="trace-hover-unpin"
            title="取消固定 (Esc)"
            @click="traceIndex.unpin()"
          >
            取消固定
          </button>
        </span>
      </header>
      <ul class="trace-hover-list">
        <li
          v-for="item in traceCounterparts"
          :key="item.targetId + item.relationType"
          class="trace-hover-item"
          @click="onCounterpartClick(item)"
        >
          <div class="trace-hover-title">{{ item.title }}</div>
          <div v-if="item.subtitle" class="trace-hover-sub">{{ item.subtitle }}</div>
          <div class="trace-hover-scores">
            <span class="trace-hover-relation">{{ item.relationType }}</span>
            <span>相关度 {{ item.relevance }}%</span>
            <span>置信 {{ item.confidence }}%</span>
          </div>
          <div v-if="item.rationale" class="trace-hover-rationale">{{ item.rationale }}</div>
        </li>
      </ul>
    </div>
    <el-dialog v-model="artifactVersionsVisible" title="本机保留的云端文件版本" width="760px">
      <el-table :data="artifactVersions">
        <el-table-column prop="entity_type" label="类型" width="150" />
        <el-table-column prop="filename" label="文件" />
        <el-table-column prop="version_number" label="版本" width="80" />
        <el-table-column label="状态" width="90"><template #default="scope">{{ scope.row.is_current ? '当前' : '保留' }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="scope"><el-button v-if="!scope.row.is_current" text @click="selectArtifactVersion(scope.row)">设为当前</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import {
  ArrowDown,
  ArrowUp,
  Back,
  ChatLineRound,
  Close,
  Connection,
  DataAnalysis,
  Document,
  DocumentAdd,
  Download,
  Files,
  FolderOpened,
  MagicStick,
  Refresh,
  Share,
  Tickets,
  Loading,
  UploadFilled,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { localCloudSyncAvailable, localHttp } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'

import { isEditableFile, fileIcon, useCode } from '@/composables/useCode'
import { useDesktop } from '@/composables/useDesktop'
import { useImport } from '@/composables/useImport'
import { useInsights } from '@/composables/useInsights'
import { usePaper } from '@/composables/usePaper'
import { useTensorFlow } from '@/composables/useTensorFlow'
import { useTrace } from '@/composables/useTrace'
import { useTraceIndex } from '@/composables/useTraceIndex'
import { useWorkspace } from '@/composables/useWorkspace'
import type { PaperMark } from '@/features/papers/trace-decorations'
import AgentPanel from '@/features/agent/AgentPanel.vue'
import PaperOutlineTree from '@/features/papers/PaperOutlineTree.vue'
import PaperReader from '@/features/papers/PaperReader.vue'
import CodeEditor from '@/features/repository/CodeEditor.vue'
import RepositoryTree from '@/features/repository/RepositoryTree.vue'
import TensorFlowCanvas from '@/features/tensor-flow/TensorFlowCanvas.vue'
import TensorFlowInspector from '@/features/tensor-flow/TensorFlowInspector.vue'
import ConflictPanel from '@/features/tracing/ConflictPanel.vue'
import EvidenceDrawer from '@/features/tracing/EvidenceDrawer.vue'
import ReportPanel from '@/features/tracing/ReportPanel.vue'
import TraceMatrix from '@/features/tracing/TraceMatrix.vue'
import type { TensorFlowNode } from '@/composables/useTensorFlow'
import type { TraceRowView } from '@/composables/useTrace'
import type { AgentUiAction } from '@/types/agent'

type BottomPanelKey = 'trace' | 'flow' | 'conflict' | 'report'
type PaneKey = 'paper' | 'code'
type ResizeMode = 'explorer' | 'editor' | 'bottom' | 'agent'
interface LocalArtifactVersionRow {
  local_version_id: number
  entity_type: 'paper_document' | 'code_repository'
  entity_public_id: string
  version_number: number
  filename: string
  is_current: boolean
}

const workspace = useWorkspace()
const auth = useAuthStore()
const sync = useSyncStore()
const cloudSyncEnabled = computed(
  () => localCloudSyncAvailable && auth.authenticated && auth.verified,
)
const workspaceStatus = computed<{ label: string; type: 'success' | 'warning' }>(() => {
  const status = sync.projectStatus({
    public_id: workspace.projectPublicId.value,
    sync_mode: workspace.syncMode.value,
  })
  if (status === 'syncing') return { label: '正在同步', type: 'warning' }
  if (status === 'pending') return { label: '待同步', type: 'warning' }
  return { label: '已同步', type: 'success' }
})
async function syncWorkspace() {
  try {
    await sync.sync()
    await workspace.loadProject()
    ElMessage.success('云同步完成')
  } catch {
    ElMessage.error('云同步失败，本地工作不受影响')
  }
}
const paper = usePaper(() => workspace.projectId.value)
const code = useCode(() => workspace.projectId.value)
const tensorFlow = useTensorFlow(() => workspace.projectId.value)
const trace = useTrace(() => workspace.projectId.value)
const traceIndex = useTraceIndex(trace.traceLinks)
const paperMarks = computed<PaperMark[]>(() =>
  [...traceIndex.paperTargets.value.values()].map((target) => ({
    targetId: target.targetId,
    blockId: target.blockId,
    quote: target.quote,
    occurrence: target.occurrence,
    status: target.status,
  })),
)
const codeTargetList = computed(() => [...traceIndex.codeTargets.value.values()])
const insights = useInsights(() => workspace.projectId.value)
const desktop = useDesktop()
const { importSteps } = useImport(
  () => paper.hasPaper.value,
  () => code.hasCode.value,
  () => tensorFlow.analysisStatus.value,
)
const repositoryStatusLabel = computed(() => {
  if (!code.hasCode.value) return '等待代码'
  if (tensorFlow.analysisStatus.value === 'ready') return '仓库已分析'
  if (tensorFlow.analysisStatus.value === 'failed') return '仓库分析失败'
  if (tensorFlow.analysisStatus.value === 'missing') return '等待本地分析'
  return '仓库分析中'
})

const activeMode = ref('审阅')
const reviewModes = ['审阅', '标注', '冲突']
const activeBottomPanel = ref<BottomPanelKey>('trace')
const bottomPanelOpen = ref(false)
const bottomPanelMaximized = ref(false)
const explorerOpen = ref(true)
const agentOpen = ref(false)
const githubUrl = ref('')
const activeExplorerView = ref<'files' | 'outline'>('files')
const paperFirst = ref(true)
const draggedPane = ref<PaneKey | null>(null)
const explorerWidth = ref(260)
const editorLeftPercent = ref(50)
const bottomPanelHeight = ref(290)
const storedAgentWidth = Number(window.localStorage.getItem('tracelab.agent.width'))
const agentWidth = ref(
  Number.isFinite(storedAgentWidth) && storedAgentWidth >= 260
    ? Math.min(storedAgentWidth, 720)
    : 420,
)
const resizeMode = ref<ResizeMode | null>(null)

const bottomTabs: Array<{ key: BottomPanelKey; label: string }> = [
  { key: 'trace', label: '追溯矩阵' },
  { key: 'flow', label: '张量流图' },
  { key: 'conflict', label: '冲突分析' },
  { key: 'report', label: '报告与质量' },
]

const evidenceDrawerVisible = ref(false)
const selectedTraceRow = ref<TraceRowView | null>(null)
const codeEditorRef = ref<InstanceType<typeof CodeEditor> | null>(null)
const paperReaderRef = ref<InstanceType<typeof PaperReader> | null>(null)
const paperInputRef = ref<HTMLInputElement | null>(null)
const codeInputRef = ref<HTMLInputElement | null>(null)
const ideBodyRef = ref<HTMLElement | null>(null)
const editorGridRef = ref<HTMLElement | null>(null)
const workAreaRef = ref<HTMLElement | null>(null)
const artifactVersionsVisible = ref(false)
const artifactVersions = ref<LocalArtifactVersionRow[]>([])

async function openArtifactVersions() {
  artifactVersions.value = (
    await localHttp.get<LocalArtifactVersionRow[]>(
      `/local-sync/projects/${workspace.projectId.value}/artifact-versions`,
    )
  ).data
  artifactVersionsVisible.value = true
}

async function selectArtifactVersion(row: LocalArtifactVersionRow) {
  await localHttp.post(
    `/local-sync/projects/${workspace.projectId.value}/artifacts/`
      + `${row.entity_type}/${row.entity_public_id}/select`,
    { local_version_id: row.local_version_id },
  )
  await openArtifactVersions()
  await Promise.allSettled([paper.loadPaperPages(), code.loadCodeTree()])
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && traceIndex.pinned.value) traceIndex.unpin()
}

onMounted(async () => {
  window.addEventListener('resize', clampAgentWidth)
  window.addEventListener('keydown', onGlobalKeydown)
  await nextTick()
  clampAgentWidth()
  if (!workspace.projectId.value || Number.isNaN(workspace.projectId.value)) return
  workspace.loadingWorkspace.value = true
  try {
    await workspace.loadProject()
    if (cloudSyncEnabled.value) void sync.refreshPending()
    await Promise.allSettled([
      paper.loadPaperPages(),
      code.loadCodeTree(),
      trace.loadTraceRows(),
      tensorFlow.loadTensorFlow(),
      insights.loadInsights(),
    ])
  } catch {
    ElMessage.error('加载项目工作台失败')
  } finally {
    workspace.loadingWorkspace.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', clampAgentWidth)
  window.removeEventListener('keydown', onGlobalKeydown)
  stopResize()
  paper.cancelPolling() // stop any in-flight parse poll so it can't hit /projects/NaN/... (422)
})

watch([explorerOpen, explorerWidth], async () => {
  await nextTick()
  clampAgentWidth()
})

function startPaneDrag(pane: PaneKey, event: DragEvent): void {
  draggedPane.value = pane
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', pane)
  }
}

function dropPane(target: PaneKey): void {
  if (draggedPane.value && draggedPane.value !== target) {
    paperFirst.value = !paperFirst.value
  }
  draggedPane.value = null
}

function startResize(mode: ResizeMode, event: PointerEvent): void {
  event.preventDefault()
  resizeMode.value = mode
  if (mode === 'bottom') bottomPanelMaximized.value = false
  document.body.style.cursor = mode === 'bottom' ? 'row-resize' : 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handleResize)
  window.addEventListener('pointerup', stopResize, { once: true })
}

function handleResize(event: PointerEvent): void {
  if (resizeMode.value === 'explorer') {
    const body = ideBodyRef.value?.getBoundingClientRect()
    if (!body) return
    explorerWidth.value = Math.round(
      Math.min(Math.max(event.clientX - body.left - 46, 190), Math.min(440, body.width * 0.42)),
    )
    return
  }
  if (resizeMode.value === 'editor') {
    const editor = editorGridRef.value?.getBoundingClientRect()
    if (!editor) return
    const percent = ((event.clientX - editor.left) / editor.width) * 100
    editorLeftPercent.value = Math.min(Math.max(percent, 22), 78)
    return
  }
  if (resizeMode.value === 'agent') {
    const body = ideBodyRef.value?.getBoundingClientRect()
    if (!body) return
    const { min, max } = agentWidthBounds(body.width)
    agentWidth.value = Math.round(Math.min(Math.max(body.right - event.clientX, min), max))
    return
  }
  if (resizeMode.value === 'bottom') {
    const workArea = workAreaRef.value?.getBoundingClientRect()
    if (!workArea) return
    bottomPanelHeight.value = Math.round(
      Math.min(Math.max(workArea.bottom - event.clientY, 150), workArea.height - 140),
    )
  }
}

function agentWidthBounds(bodyWidth: number): { min: number; max: number } {
  const overlay = window.matchMedia('(max-width: 980px)').matches
  const explorerSpace = explorerOpen.value ? explorerWidth.value + 4 : 0
  const available = overlay
    ? bodyWidth - 46
    : bodyWidth - 46 - explorerSpace - 320
  const max = Math.max(260, Math.min(720, available))
  return { min: Math.min(320, max), max }
}

function clampAgentWidth(): void {
  const body = ideBodyRef.value?.getBoundingClientRect()
  if (!body) return
  const { min, max } = agentWidthBounds(body.width)
  agentWidth.value = Math.round(Math.min(Math.max(agentWidth.value, min), max))
}

function stopResize(): void {
  if (resizeMode.value === 'agent') {
    window.localStorage.setItem('tracelab.agent.width', String(agentWidth.value))
  }
  resizeMode.value = null
  window.removeEventListener('pointermove', handleResize)
  window.removeEventListener('pointerup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function onOutlineSelect(sectionId: string): void {
  paper.selectSection(sectionId)
}

function openBottomPanel(tab: BottomPanelKey): void {
  activeBottomPanel.value = tab
  bottomPanelOpen.value = true
}

const hasGeneratedTrace = computed(
  () => trace.mode.value === 'agent' || trace.traceLinks.value.length > 0,
)

function openTraceAndGenerate(): void {
  openBottomPanel('trace')
  // First run may reuse an existing job; an explicit regenerate forces a fresh pass.
  void generateAgentAnalysis(hasGeneratedTrace.value)
}

async function generateAgentAnalysis(force = false): Promise<void> {
  await trace.generateSuggestions(force)
  await tensorFlow.loadTensorFlow({ force: true })
}

async function handleImportAction(stepIndex: string): Promise<void> {
  if (stepIndex === '01') {
    if (desktop.isDesktop.value) {
      const file = await desktop.pickPdfFile()
      if (file) {
        const success = await paper.handleUpload(file)
        if (success) await reloadDerivedViews()
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
        if (success) await reloadDerivedViews()
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
  if (success) await reloadDerivedViews()
}

async function onCodeSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const success = await code.handleUpload(file)
  if (success) await reloadDerivedViews()
}

function onTensorNodeClick(node: TensorFlowNode): void {
  tensorFlow.selectNode(node)
  void jumpToCode(node.sourcePath, node.lineStart)
}

function onTensorJumpToCode(node: TensorFlowNode): void {
  void jumpToCode(node.sourcePath, node.lineStart)
}

async function jumpToCode(path: string, line: number): Promise<void> {
  await code.openCodeFile(path)
  await nextTick()
  codeEditorRef.value?.goToLine(line)
}

function onTraceRowSelect(row: TraceRowView): void {
  selectedTraceRow.value = row
  evidenceDrawerVisible.value = true
}

// Hovering a matrix row lights up the same relation on both panes via the shared index.
function hoverTraceRow(row: TraceRowView): void {
  if (!row.id) return
  const link = trace.traceLinks.value.find((item) => item.id === row.id)
  const paperTargetId =
    link?.paper_target_id || link?.evidence.find((item) => item.side === 'paper')?.target_id
  if (paperTargetId) traceIndex.hoverPaper(paperTargetId)
}

async function jumpToTracePaper(row: TraceRowView): Promise<void> {
  const evidence = row.evidence.find((item) => item.side === 'paper')
  await nextTick()
  const found = paperReaderRef.value?.scrollToBlock(row.paper, evidence?.quote || '')
  if (!found) ElMessage.warning('论文精确锚点不可用，已保留当前阅读位置')
}

async function jumpToTraceCode(row: TraceRowView): Promise<void> {
  const evidence = row.evidence.find((item) => item.side === 'code')
  const path = evidence?.path || row.code.split('::', 1)[0]
  if (!path) return
  await jumpToCode(path, evidence?.line_start || 1)
}

interface TraceCounterpart {
  targetId: string
  title: string
  subtitle: string
  relationType: string
  relevance: number
  confidence: number
  rationale: string
  path?: string
  line?: number
}

// Counterpart targets of the active trace target, ranked by relevance, for the hover popover.
const traceCounterparts = computed<TraceCounterpart[]>(() => {
  const side = traceIndex.activeSide.value
  if (!side) return []
  return traceIndex.activeLinks.value.map((link) => {
    if (side === 'paper') {
      const code = link.evidence.find((item) => item.side === 'code')
      return {
        targetId: link.code_target_id || code?.target_id || link.id,
        title: link.code_symbol_id,
        subtitle: code?.path || '',
        relationType: link.relation_type,
        relevance: Math.round(link.relevance * 100),
        confidence: Math.round(link.confidence * 100),
        rationale: link.rationale,
        path: code?.path,
        line: code?.match_line_start ?? code?.line_start ?? 1,
      }
    }
    const paper = link.evidence.find((item) => item.side === 'paper')
    return {
      targetId: link.paper_target_id || paper?.target_id || link.id,
      title: paper?.quote || link.paper_block_id,
      subtitle: `${link.paper_block_id}${paper?.target_type ? ` · ${paper.target_type}` : ''}`,
      relationType: link.relation_type,
      relevance: Math.round(link.relevance * 100),
      confidence: Math.round(link.confidence * 100),
      rationale: link.rationale,
    }
  })
})

async function onCounterpartClick(item: TraceCounterpart): Promise<void> {
  if (traceIndex.activeSide.value === 'paper' && item.path) {
    await jumpToCode(item.path, item.line || 1)
  }
}

// When a paper target is pinned, open the top counterpart file so its code highlight shows.
watch(
  () => [traceIndex.pinned.value, traceIndex.activeSide.value, traceIndex.activeTargetId.value],
  async () => {
    if (!traceIndex.pinned.value || traceIndex.activeSide.value !== 'paper') return
    const codeEv = traceIndex.activeLinks.value[0]?.evidence.find((item) => item.side === 'code')
    if (codeEv?.path) {
      await jumpToCode(codeEv.path, codeEv.match_line_start ?? codeEv.line_start ?? 1)
    }
  },
)

async function onEvidenceConfirm(row: TraceRowView): Promise<void> {
  if (!row.id) {
    ElMessage.info('当前为预览数据，生成追溯候选后才能审阅')
    return
  }
  await trace.reviewTrace(row.id, 'accepted')
  evidenceDrawerVisible.value = false
}

async function onEvidenceReject(row: TraceRowView): Promise<void> {
  if (!row.id) {
    ElMessage.info('当前为预览数据，生成追溯候选后才能审阅')
    return
  }
  await trace.reviewTrace(row.id, 'rejected')
  evidenceDrawerVisible.value = false
}

async function onGitHubImport(): Promise<void> {
  const url = githubUrl.value.trim()
  if (!url) return
  const success = await code.handleGitHubImport(url)
  if (success) {
    githubUrl.value = ''
    await reloadDerivedViews()
  }
}

async function onSaveCode(): Promise<void> {
  await code.saveEditorBuffer()
  await reloadDerivedViews()
}

async function reloadDerivedViews(): Promise<void> {
  await Promise.allSettled([
    trace.loadTraceRows(),
    tensorFlow.loadTensorFlow({ force: true }),
    insights.loadInsights(),
  ])
}

async function reloadAfterAgentAction(): Promise<void> {
  await Promise.allSettled([code.loadCodeTree(), reloadDerivedViews()])
}

async function handleAgentUiAction(action: AgentUiAction): Promise<void> {
  if (action.type === 'open_code' && action.path) {
    await jumpToCode(action.path, action.line || 1)
    return
  }
  if (action.type === 'open_paper' && action.block_id) {
    await nextTick()
    const found = paperReaderRef.value?.scrollToBlock(action.block_id, action.quote || '')
    if (!found) ElMessage.warning('论文精确锚点不可用')
    return
  }
  if (action.type === 'focus_architecture') {
    openBottomPanel('flow')
    await tensorFlow.loadTensorFlow({
      view: action.view || 'architecture',
      rootSymbol: action.root_symbol || null,
    })
  }
}

watch(activeBottomPanel, (tab) => {
  if (tab === 'flow') void tensorFlow.loadTensorFlow()
  if (tab === 'conflict' || tab === 'report') void insights.loadInsights()
})
</script>

<style scoped>
.ide-workbench {
  --ide-border: #d8dee6;
  --ide-muted: #6b7785;
  --ide-surface: #ffffff;
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: 42px minmax(0, 1fr) 23px;
  overflow: hidden;
  background: #f5f7f9;
  color: #26323d;
}

.command-bar,
.status-bar,
.sidebar-header,
.pane-tab-strip,
.bottom-panel-header {
  display: flex;
  align-items: center;
}

.command-bar {
  z-index: 4;
  justify-content: space-between;
  gap: 12px;
  padding: 0 8px;
  border-bottom: 1px solid var(--ide-border);
  background: #ffffff;
}

.project-breadcrumb,
.command-actions,
.project-root-row,
.repository-stats,
.status-bar span,
.pane-tab,
.panel-controls {
  display: flex;
  align-items: center;
}

.project-breadcrumb {
  min-width: 0;
  gap: 6px;
  color: var(--ide-muted);
  font-size: 12px;
  white-space: nowrap;
}

.project-name {
  max-width: 180px;
  overflow: hidden;
  color: #26323d;
  font-weight: 700;
  text-overflow: ellipsis;
}

.breadcrumb-separator {
  color: #a0a9b3;
}

.mode-switch {
  display: flex;
  padding: 2px;
  border: 1px solid var(--ide-border);
  border-radius: 5px;
  background: #f6f8fa;
}

.mode-switch button {
  padding: 4px 10px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: #667382;
  cursor: pointer;
  font-size: 12px;
}

.mode-switch button.active {
  background: #ffffff;
  color: #147866;
  box-shadow: 0 1px 3px rgba(28, 43, 54, 0.12);
  font-weight: 700;
}

.command-actions {
  gap: 4px;
  white-space: nowrap;
}

.ide-body {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.activity-bar {
  z-index: 6;
  display: flex;
  width: 46px;
  flex: 0 0 46px;
  flex-direction: column;
  align-items: stretch;
  padding: 4px 0;
  border-right: 1px solid var(--ide-border);
  background: #f8f9fb;
}

.activity-button {
  position: relative;
  display: grid;
  width: 100%;
  height: 43px;
  place-items: center;
  border: 0;
  border-left: 2px solid transparent;
  background: transparent;
  color: #6b7785;
  cursor: pointer;
}

.activity-button:hover {
  color: #26323d;
  background: #eef2f4;
}

.activity-button.active {
  border-left-color: #1f8f78;
  color: #1f8f78;
  background: #edf7f4;
}

.activity-badge {
  position: absolute;
  right: 4px;
  bottom: 4px;
  display: grid;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  place-items: center;
  border-radius: 8px;
  background: #1f8f78;
  color: #ffffff;
  font-size: 9px;
}

.activity-spacer {
  flex: 1;
}

.explorer-sidebar,
.agent-sidebar {
  z-index: 3;
  display: grid;
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--ide-border);
  background: #f8fafb;
}

.explorer-sidebar {
  flex: 0 0 auto;
  grid-template-rows: 35px 29px minmax(0, 1fr);
}

.explorer-resize-handle,
.agent-resize-handle,
.editor-resize-handle,
.bottom-resize-handle {
  z-index: 8;
  background: transparent;
  transition: background 0.12s ease;
}

.explorer-resize-handle {
  width: 4px;
  flex: 0 0 4px;
  margin-left: -4px;
  cursor: col-resize;
}

.agent-resize-handle {
  width: 5px;
  flex: 0 0 5px;
  margin-right: -5px;
  cursor: col-resize;
}

.explorer-resize-handle:hover,
.agent-resize-handle:hover,
.editor-resize-handle:hover,
.bottom-resize-handle:hover {
  background: #1f8f78;
}

.explorer-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-bottom: 1px solid var(--ide-border);
  background: #f3f6f8;
}

.explorer-tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #6c7885;
  cursor: pointer;
  font-size: 10px;
}

.explorer-tabs button.active {
  border-bottom-color: #1f8f78;
  background: #ffffff;
  color: #176f60;
  font-weight: 700;
}

.explorer-content {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.file-explorer-content {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
}

.outline-content {
  display: grid;
}

.sidebar-header {
  justify-content: space-between;
  min-height: 35px;
  padding: 0 7px 0 12px;
  border-bottom: 1px solid var(--ide-border);
  color: #5f6b78;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.project-overview {
  border-bottom: 1px solid var(--ide-border);
}

.project-root-row {
  gap: 7px;
  height: 30px;
  padding: 0 10px;
  font-size: 12px;
}

.project-root-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-state-list {
  display: grid;
  padding: 2px 6px 7px;
}

.import-state {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 6px;
  align-items: center;
  padding: 5px 6px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #657281;
  text-align: left;
}

.import-state:not(:disabled) {
  cursor: pointer;
}

.import-state:not(:disabled):hover {
  background: #edf2f4;
}

.import-state > span {
  color: #9aa4ae;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
}

.import-state div {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.import-state strong,
.import-state small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-state strong {
  font-size: 11px;
  font-weight: 600;
}

.import-state small {
  color: #8995a1;
  font-size: 10px;
}

.import-state.ready > span,
.import-state.ready small {
  color: #1f8f78;
}

.github-import {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 5px;
  padding: 7px;
  border-bottom: 1px solid var(--ide-border);
}

.repository-stats {
  flex-wrap: wrap;
  gap: 8px;
  padding: 6px 9px;
  border-bottom: 1px solid var(--ide-border);
  color: #75818e;
  font-size: 10px;
}

.tree-container {
  min-height: 0;
  overflow: hidden;
}

.tree-container :deep(.file-tree) {
  height: 100%;
  gap: 5px;
  padding: 7px 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.tree-container :deep(.tree-head span) {
  display: none;
}

.tree-container :deep(.tree-head strong),
.tree-container :deep(.ignore-summary strong) {
  font-size: 11px;
}

.tree-container :deep(.file-node) {
  min-height: 25px;
  padding-top: 3px;
  padding-bottom: 3px;
  border-radius: 3px;
  font-size: 12px;
}

.tree-container :deep(.ignore-summary) {
  font-size: 10px;
}

.work-area {
  display: grid;
  min-width: 0;
  min-height: 0;
  flex: 1;
  grid-template-rows: minmax(0, 1fr) auto;
  overflow: hidden;
  background: #ffffff;
}

.editor-grid {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns:
    minmax(0, var(--left-pane-width, 50%))
    5px
    minmax(0, calc(100% - var(--left-pane-width, 50%) - 5px));
  overflow: hidden;
}

.editor-resize-handle {
  width: 5px;
  cursor: col-resize;
  border-right: 1px solid var(--ide-border);
  border-left: 1px solid var(--ide-border);
}

.editor-pane {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: 32px minmax(0, 1fr);
  overflow: hidden;
  background: #ffffff;
}

.pane-tab-strip {
  min-width: 0;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid var(--ide-border);
  background: #f6f8fa;
}

.draggable-tab {
  cursor: grab;
}

.draggable-tab:active {
  cursor: grabbing;
}

.pane-tab {
  min-width: 0;
  height: 32px;
  gap: 6px;
  padding: 0 11px;
  overflow: hidden;
  border-right: 1px solid var(--ide-border);
  color: #566371;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pane-tab.active {
  border-top: 2px solid #1f8f78;
  background: #ffffff;
  color: #26323d;
}

.pane-meta,
.dirty-indicator {
  flex: 0 0 auto;
  padding-right: 9px;
  color: #7b8793;
  font-size: 10px;
}

.dirty-indicator {
  color: #a15f00;
}

.paper-pane :deep(.paper-panel) {
  height: 100%;
  min-height: 0;
  max-height: none;
  gap: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
}

.paper-pane :deep(.panel-title) {
  display: none;
}

.paper-pane :deep(.pdf-toolbar) {
  min-height: 34px;
  padding: 5px 8px;
  border-bottom: 1px solid var(--ide-border);
  border-radius: 0;
}

.paper-pane :deep(.pdf-reader) {
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 0;
}

.paper-pane :deep(.page-rail) {
  gap: 4px;
  padding: 6px 5px;
  border-right: 1px solid var(--ide-border);
  background: #f7f9fa;
}

.paper-pane :deep(.page-rail button) {
  padding: 5px;
  border-radius: 3px;
}

.paper-pane :deep(.paper-scroll) {
  border: 0;
  border-radius: 0;
}

.paper-pane :deep(.paper-page) {
  padding: 24px 30px;
  box-shadow: none;
}

.paper-pane :deep(.paper-page h3) {
  font-size: 21px;
}

.code-pane :deep(.editor-shell) {
  height: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
}

.code-pane :deep(.editor-tabs),
.code-pane :deep(.editor-footer) {
  min-height: 32px;
  padding: 5px 9px;
  font-size: 11px;
}

.bottom-panel {
  position: relative;
  display: grid;
  height: clamp(230px, 32vh, 340px);
  min-height: 190px;
  grid-template-rows: 34px minmax(0, 1fr);
  overflow: hidden;
  border-top: 1px solid #bfc8d2;
  background: #ffffff;
}

.bottom-resize-handle {
  position: absolute;
  top: -3px;
  right: 0;
  left: 0;
  height: 6px;
  cursor: row-resize;
}

.bottom-panel.maximized {
  height: min(62vh, 680px);
}

.bottom-panel-header {
  justify-content: space-between;
  padding: 0 6px 0 10px;
  border-bottom: 1px solid var(--ide-border);
  background: #f8f9fb;
}

.bottom-tabs {
  display: flex;
  height: 100%;
  gap: 18px;
}

.bottom-tabs button {
  display: flex;
  height: 100%;
  align-items: center;
  gap: 5px;
  padding: 0 1px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #657281;
  cursor: pointer;
  font-size: 11px;
}

.bottom-tabs button.active {
  border-bottom-color: #1f8f78;
  color: #1f8f78;
  font-weight: 700;
}

.bottom-tabs button span {
  display: grid;
  min-width: 16px;
  height: 16px;
  padding: 0 3px;
  place-items: center;
  border-radius: 8px;
  background: #e6ecef;
  color: #667382;
  font-size: 9px;
}

.panel-controls {
  gap: 1px;
}

.bottom-panel-content {
  min-height: 0;
  overflow: auto;
}

.trace-panel-layout {
  display: grid;
  min-height: 100%;
  grid-template-columns: minmax(700px, 1fr) 220px;
}

.trace-panel-layout :deep(.trace-matrix) {
  padding: 9px 12px;
  border: 0;
  border-radius: 0;
}

.trace-panel-layout :deep(.trace-matrix header) {
  margin-bottom: 5px;
}

.trace-panel-layout :deep(.trace-matrix h2) {
  font-size: 14px;
}

.trace-panel-layout :deep(.trace-matrix p) {
  display: none;
}

.trace-panel-layout :deep(.trace-row) {
  min-width: 700px;
  padding-top: 7px;
  padding-bottom: 7px;
  font-size: 11px;
}

.trace-summary {
  display: grid;
  align-content: start;
  gap: 8px;
  padding: 12px;
  border-left: 1px solid var(--ide-border);
  background: #f8fafb;
  color: #667382;
  font-size: 11px;
}

.trace-summary strong {
  color: #26323d;
  font-size: 12px;
}

.trace-summary p {
  margin: 0;
  line-height: 1.5;
}

.agent-activity {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #eef4ff;
  color: #2b4a86;
  font-size: 11px;
}

.agent-activity-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spin {
  animation: agent-spin 1s linear infinite;
}

@keyframes agent-spin {
  to {
    transform: rotate(360deg);
  }
}

.agent-log {
  margin: 0;
  padding: 6px 8px;
  max-height: 148px;
  overflow-y: auto;
  list-style: none;
  border: 1px solid #e6ebf0;
  border-radius: 6px;
  background: #ffffff;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
  line-height: 1.7;
  color: #55636f;
}

.agent-degraded {
  color: #b64a3c;
}

.tensor-flow-layout {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: minmax(720px, 1fr) 300px;
}

.tensor-flow-layout :deep(.tensor-flow-board),
.tensor-flow-layout :deep(.flow-inspector) {
  padding: 10px 12px;
  border: 0;
  border-radius: 0;
}

.tensor-flow-layout :deep(.tensor-flow-board h2),
.tensor-flow-layout :deep(.flow-inspector h2) {
  font-size: 14px;
}

.tensor-flow-layout :deep(.tensor-flow-board > header p),
.tensor-flow-layout :deep(.api-note) {
  display: none;
}

.tensor-flow-layout :deep(.tensor-flow-canvas) {
  min-height: 0;
  max-height: none;
  margin-top: 7px;
  overflow: hidden;
  border-radius: 3px;
}

.tensor-flow-layout :deep(.flow-inspector) {
  min-height: 0;
  overflow: auto;
  border-left: 1px solid var(--ide-border);
  background: #f8fafb;
}

.bottom-panel-content :deep(.placeholder-notice) {
  margin: 8px 10px 0;
  padding: 6px 9px;
  font-size: 11px;
}

.bottom-panel-content :deep(.conflict-grid),
.bottom-panel-content :deep(.report-layout) {
  gap: 8px;
  padding: 9px 10px;
}

.bottom-panel-content :deep(.conflict-card),
.bottom-panel-content :deep(.report-card) {
  gap: 7px;
  padding: 10px;
  border-radius: 4px;
}

.bottom-panel-content :deep(.conflict-card h2) {
  font-size: 13px;
}

.bottom-panel-content :deep(.conflict-card p),
.bottom-panel-content :deep(.report-card p) {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
}

.bottom-panel-content :deep(.report-card strong) {
  font-size: 20px;
}

.report-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-bottom: 1px solid var(--ide-border);
  color: #667382;
  font-size: 11px;
}

.agent-sidebar {
  width: 420px;
  flex: 0 0 420px;
  grid-template-rows: 35px minmax(0, 1fr);
  border-right: 0;
  border-left: 1px solid var(--ide-border);
  background: #ffffff;
}

.agent-content {
  min-height: 0;
  overflow: hidden;
}

.status-bar {
  gap: 14px;
  padding: 0 9px;
  overflow: hidden;
  background: #1f8f78;
  color: #ffffff;
  font-size: 10px;
  white-space: nowrap;
}

.status-bar span {
  gap: 4px;
}

.status-spacer {
  flex: 1;
}

@media (max-width: 1200px) {
  .explorer-sidebar {
    width: 230px;
    flex-basis: 230px;
  }

  .command-bar .mode-switch {
    display: none;
  }
}

@media (max-width: 980px) {
  .explorer-resize-handle {
    display: none;
  }

  .explorer-sidebar,
  .agent-sidebar {
    position: absolute;
    top: 0;
    bottom: 0;
    box-shadow: 0 8px 24px rgba(28, 43, 54, 0.18);
  }

  .explorer-sidebar {
    left: 46px;
    width: min(300px, calc(100vw - 92px));
  }

  .agent-sidebar {
    right: 0;
    width: min(440px, calc(100vw - 46px));
    max-width: calc(100vw - 46px);
  }

  .agent-resize-handle {
    position: absolute;
    top: 0;
    right: min(var(--agent-width), calc(100vw - 46px));
    bottom: 0;
    margin-right: 0;
  }
}

@media (max-width: 760px) {
  .project-breadcrumb > span:not(.project-name),
  .command-actions .el-button span > span {
    display: none;
  }

  .command-actions {
    margin-left: auto;
  }

  .editor-grid {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(300px, 1fr) minmax(320px, 1fr);
    overflow: auto;
  }

  .editor-resize-handle {
    display: none;
  }

  .paper-pane {
    border-right: 0;
    border-bottom: 1px solid var(--ide-border);
  }

  .bottom-tabs {
    gap: 10px;
  }

  .bottom-tabs button {
    font-size: 10px;
  }

  .status-bar span:nth-of-type(2),
  .status-bar span:nth-of-type(3) {
    display: none;
  }
}

.trace-hover-popover {
  position: fixed;
  right: 18px;
  bottom: 46px;
  z-index: 2200;
  width: 340px;
  max-height: 52vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #cdd6df;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 12px 34px rgba(19, 35, 47, 0.18);
}

.trace-hover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border-bottom: 1px solid #e6ebf0;
  background: #f7f9fb;
  font-size: 12px;
  font-weight: 600;
  color: #26323d;
}

.trace-hover-count {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
  color: #7a8794;
  font-size: 11px;
}

.trace-hover-unpin {
  border: 1px solid #d8dee6;
  border-radius: 4px;
  background: #fff;
  padding: 1px 7px;
  cursor: pointer;
  color: #586675;
  font: inherit;
  font-size: 11px;
}

.trace-hover-list {
  margin: 0;
  padding: 6px;
  overflow-y: auto;
  list-style: none;
}

.trace-hover-item {
  padding: 8px 10px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 120ms ease;
}

.trace-hover-item:hover {
  background: #eef4ff;
}

.trace-hover-title {
  font-size: 12px;
  font-weight: 600;
  color: #1c2b38;
  word-break: break-word;
}

.trace-hover-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #7a8794;
  word-break: break-all;
}

.trace-hover-scores {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 5px;
  font-size: 11px;
  color: #55636f;
}

.trace-hover-relation {
  padding: 0 6px;
  border-radius: 999px;
  background: #e6efff;
  color: #3061c2;
  font-weight: 600;
}

.trace-hover-rationale {
  margin-top: 5px;
  font-size: 11px;
  line-height: 1.5;
  color: #6b7785;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
