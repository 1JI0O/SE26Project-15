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
        <el-tooltip content="只给 GitHub 链接，工作台自己拉取代码" placement="bottom">
          <el-button
            size="small"
            :icon="Download"
            :loading="code.importingGithub.value"
            @click="promptGitHubImport"
          >
            <span>GitHub</span>
          </el-button>
        </el-tooltip>
        <el-button size="small" @click="openArtifactVersions">版本历史</el-button>
        <el-tooltip
          :content="
            debug.enabled.value
              ? '调试模式已开启：所有报错都会带完整信息记录，点击关闭'
              : '开启调试模式：出错时输出完整堆栈与服务端返回，便于定位问题'
          "
          placement="bottom"
        >
          <el-button
            size="small"
            :type="debug.enabled.value ? 'warning' : 'default'"
            :plain="debug.enabled.value"
            @click="toggleDebug"
          >
            <span>调试{{ debug.enabled.value ? '中' : '' }}</span>
          </el-button>
        </el-tooltip>
        <el-button
          v-if="debug.enabled.value && !debug.panelOpen.value"
          size="small"
          text
          @click="debug.panelOpen.value = true"
        >
          输出({{ debug.entries.value.length }})
        </el-button>
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
        <el-tooltip content="追加追溯关系" placement="right">
          <button
            :class="['activity-button', { active: annotation.active }]"
            aria-label="追加追溯关系"
            @click="startAnnotation()"
          >
            <el-icon :size="21"><EditPen /></el-icon>
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
        <el-tooltip v-if="desktop.isDesktop.value" content="终端" placement="right">
          <button
            :class="['activity-button', { active: bottomPanelOpen && activeBottomPanel === 'terminal' }]"
            aria-label="终端"
            @click="openBottomPanel('terminal')"
          >
            <el-icon :size="21"><Monitor /></el-icon>
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
            :observed-section-id="paper.observedSectionId.value"
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
        <AnnotationGuide />
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
              :pdf-url="paper.paperDocument.value?.pdf_url || null"
              :active-section-id="paper.activeSectionId.value"
              :has-paper="paper.hasPaper.value"
              :loading="paper.loading.value"
              :error="paper.error.value"
              :source="paper.paperDocument.value?.source || ''"
              :parse-status="paper.parseStatus.value"
              :blocks="paper.paperDocument.value?.blocks || []"
              :trace-targets="paperMarks"
              :active-target-ids="traceIndex.activePaperTargetIds.value"
              :hover-target-ids="traceIndex.hoverPaperTargetIds.value"
              @select-section="paper.selectSection"
              @observe-section="paper.observeSection"
              @retry="paper.loadPaperPages"
              @trace-hover="(id: string) => traceIndex.hoverTarget('paper', id)"
              @trace-leave="traceIndex.clearHover"
              @trace-pin="(id: string) => traceIndex.selectTarget('paper', id)"
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
              :hover-target-ids="traceIndex.hoverCodeTargetIds.value"
              :reveal-active="false"
              :lsp-enabled="desktop.isDesktop.value && lspReady"
              :lsp-client="lspClient"
              :lsp-checkout-root="lspCheckoutRoot"
              @change="code.handleEditorInput"
              @save="onSaveCode"
              @trace-hover="(id: string) => traceIndex.hoverTarget('code', id)"
              @trace-leave="traceIndex.clearHover"
              @trace-pin="(id: string) => traceIndex.selectTarget('code', id)"
              @goto-definition="onGotoDefinition"
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

          <div
            :class="[
              'bottom-panel-content',
              { 'trace-panel-content': activeBottomPanel === 'trace' },
            ]"
          >
            <div
              v-if="activeBottomPanel === 'trace'"
              ref="tracePanelRef"
              class="trace-panel-layout"
              :style="{ '--trace-summary-width': `${traceSummaryWidth}px` }"
            >
              <div class="trace-matrix-pane">
                <TraceMatrix
                  :rows="trace.traceRows.value"
                  :loading="trace.loading.value"
                  :error="trace.error.value"
                  :mode="trace.mode.value"
                  :degraded="trace.degraded.value"
                  :analyzing="trace.generating.value"
                  :published-count="trace.publishedLinkCount.value"
                  :selected-id="traceIndex.selectedLinkId.value"
                  @review="trace.reviewTrace"
                  @review-batch="trace.reviewBatch"
                  @select-row="onTraceRowSelect"
                  @hover-row="hoverTraceRow"
                  @leave-row="traceIndex.clearHover"
                />
              </div>
              <div
                class="trace-summary-resize-handle"
                role="separator"
                aria-label="调整追溯矩阵与分析栏宽度"
                aria-orientation="vertical"
                @pointerdown="startResize('traceSummary', $event)"
              />
              <div
                ref="traceDetailRef"
                class="trace-detail-column"
                :style="{
                  '--trace-agent-share': `${traceAgentRatio}fr`,
                  '--trace-preview-share': `${100 - traceAgentRatio}fr`,
                }"
              >
                <aside class="trace-summary">
                  <strong>Agent 分析</strong>
                  <span v-if="trace.mode.value">{{ trace.mode.value }}</span>
                  <span v-else>Agent 自主读取论文与代码证据</span>

                  <template v-if="trace.generating.value">
                    <div class="agent-activity">
                      <el-icon class="spin"><Loading /></el-icon>
                      <span class="agent-activity-text">{{ trace.analysisActivity.value || '启动中…' }}</span>
                    </div>
                    <!-- Steps are discrete with no reliable denominator (soft target + hard cap),
                         so show the current step only and an indeterminate running bar, not N/100. -->
                    <div v-if="trace.analysisStep.value" class="agent-step">
                      <span>第 {{ trace.analysisStep.value }} 步</span>
                      <span class="agent-step-bar"><i /></span>
                    </div>
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
                  <div class="trace-summary-actions">
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
                    <el-button
                      v-if="trace.generating.value"
                      size="small"
                      type="warning"
                      plain
                      :loading="trace.cancelling.value"
                      @click="trace.cancelAnalysis"
                    >
                      {{ trace.cancelling.value ? '正在中止…' : '中止' }}
                    </el-button>
                  </div>
                </aside>

                <div
                  class="trace-preview-resize-handle"
                  role="separator"
                  aria-label="调整 Agent 分析与关系预览高度"
                  aria-orientation="horizontal"
                  @pointerdown="startResize('tracePreview', $event)"
                />

                <div class="trace-preview-pane">
                  <TraceRelationPreview
                    :hovered-summary="traceIndex.hoveredSummary.value"
                    :selected-summary="traceIndex.selectedSummary.value"
                    :paper-markdown="paper.paperDocument.value?.markdown || ''"
                    :selected-paper-unresolved="selectedPaperUnresolved"
                    @unselect="traceIndex.unselect"
                  />
                </div>
              </div>
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
              :summary="insights.changeSummary.value"
              :report="insights.report.value"
              :loading="insights.loading.value"
              :generating="insights.generating.value"
              :cancelling="insights.cancelling.value"
              :progress="insights.progress.value"
              :activity="insights.analysisActivity.value"
              :analysis-step="insights.analysisStep.value"
              :analysis-steps="insights.analysisSteps.value"
              :error="insights.error.value"
              @analyze="onStartConflictAnalysis"
              @cancel="onCancelConflictAnalysis"
              @open-code="jumpToCode"
              @open-paper="onConflictOpenPaper"
              @open-trace="onConflictOpenTrace"
            />

            <DesktopTerminal
              v-else-if="activeBottomPanel === 'terminal' && desktop.isDesktop.value"
              :project-id="workspace.projectId.value"
            />
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

    <AnnotationDialog />
    <DebugPanel />
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
  Document,
  DocumentAdd,
  Download,
  Files,
  FolderOpened,
  Refresh,
  Share,
  Tickets,
  Loading,
  UploadFilled,
  Warning,
  Monitor,
  EditPen,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { localCloudSyncAvailable, localHttp } from '@/api/http'
import { resolveDefinition } from '@/api/repository-api'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'
import { useAnnotationStore } from '@/stores/annotation'

import { isEditableFile, fileIcon, useCode } from '@/composables/useCode'
import { useDebug } from '@/composables/useDebug'
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
import AnnotationDialog from '@/features/tracing/AnnotationDialog.vue'
import AnnotationGuide from '@/features/tracing/AnnotationGuide.vue'
import DebugPanel from '@/components/DebugPanel.vue'
import PaperOutlineTree from '@/features/papers/PaperOutlineTree.vue'
import PaperReader from '@/features/papers/PaperReader.vue'
import CodeEditor from '@/features/repository/CodeEditor.vue'
import { useDesktopPythonLsp } from '@/features/repository/useDesktopPythonLsp'
import RepositoryTree from '@/features/repository/RepositoryTree.vue'
import TensorFlowCanvas from '@/features/tensor-flow/TensorFlowCanvas.vue'
import TensorFlowInspector from '@/features/tensor-flow/TensorFlowInspector.vue'
import ConflictPanel from '@/features/tracing/ConflictPanel.vue'
import DesktopTerminal from '@/features/terminal/DesktopTerminal.vue'
import EvidenceDrawer from '@/features/tracing/EvidenceDrawer.vue'
import TraceMatrix from '@/features/tracing/TraceMatrix.vue'
import TraceRelationPreview from '@/features/tracing/TraceRelationPreview.vue'
import type { TensorFlowNode } from '@/composables/useTensorFlow'
import type { TraceRowView } from '@/composables/useTrace'
import type { AgentUiAction } from '@/types/agent'
import 'katex/dist/katex.min.css'

type BottomPanelKey = 'trace' | 'flow' | 'conflict' | 'terminal'
type PaneKey = 'paper' | 'code'
type ResizeMode =
  | 'explorer'
  | 'editor'
  | 'bottom'
  | 'agent'
  | 'traceSummary'
  | 'tracePreview'
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
const annotation = useAnnotationStore()
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
    targetType: target.targetType,
    multiplicity: target.multiplicity,
    fanoutCount: target.fanoutCount,
  })),
)
const codeTargetList = computed(() => [...traceIndex.codeTargets.value.values()])
// True when the selected relation's paper side could not be anchored in the DOM (backend never
// resolved the block anchor and quote fallback missed too) — the preview pane says so explicitly
// instead of showing a paper quote that has no visible highlight.
const selectedPaperUnresolved = computed(() => {
  const paperTargetId = traceIndex.selectedSummary.value?.paper.targetId
  if (!paperTargetId) return false
  return paperReaderRef.value?.unresolvedTargetIds?.has(paperTargetId) ?? false
})
const insights = useInsights(() => workspace.projectId.value)
const desktop = useDesktop()

async function openCodeRelativePath(path: string): Promise<void> {
  await code.openCodeFile(path)
}

const { lspClient, lspCheckoutRoot, lspReady } = useDesktopPythonLsp(
  () => workspace.projectId.value,
  openCodeRelativePath,
)

const debug = useDebug()
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
// Layout box captured at trace-summary drag start (measures from a stable right edge).
let traceLayoutRect: DOMRect | null = null
// Right-column box captured at the vertical drag start so ratio math stays stable.
let traceDetailRect: DOMRect | null = null

const TRACE_SUMMARY_MIN = 300
const TRACE_SUMMARY_MAX = 520
const TRACE_SUMMARY_DEFAULT = 360
const TRACE_MATRIX_MIN = 280
const TRACE_SUMMARY_NARROW_MIN = 220
const TRACE_SECTION_MIN_HEIGHT = 72
const TRACE_SPLITTER_SIZE = 5
const storedTraceSummaryWidth = Number(window.localStorage.getItem('tracelab.traceSummary.width'))
const traceSummaryWidth = ref(
  Number.isFinite(storedTraceSummaryWidth) && storedTraceSummaryWidth >= 180
    ? Math.min(Math.max(storedTraceSummaryWidth, TRACE_SUMMARY_MIN), TRACE_SUMMARY_MAX)
    : TRACE_SUMMARY_DEFAULT,
)
const storedTraceAgentRatio = Number(
  window.localStorage.getItem('tracelab.tracePreview.agentRatio'),
)
const traceAgentRatio = ref(
  Number.isFinite(storedTraceAgentRatio) && storedTraceAgentRatio >= 20
    ? Math.min(Math.max(storedTraceAgentRatio, 20), 80)
    : 50,
)

const bottomTabs = computed<Array<{ key: BottomPanelKey; label: string }>>(() => {
  const tabs: Array<{ key: BottomPanelKey; label: string }> = [
    { key: 'trace', label: '追溯矩阵' },
    { key: 'flow', label: '张量流图' },
    { key: 'conflict', label: '冲突分析' },
  ]
  if (desktop.isDesktop.value) {
    tabs.push({ key: 'terminal', label: '终端' })
  }
  return tabs
})

const evidenceDrawerVisible = ref(false)
const selectedTraceRow = ref<TraceRowView | null>(null)
const codeEditorRef = ref<InstanceType<typeof CodeEditor> | null>(null)
const paperReaderRef = ref<InstanceType<typeof PaperReader> | null>(null)
const paperInputRef = ref<HTMLInputElement | null>(null)
const codeInputRef = ref<HTMLInputElement | null>(null)
const ideBodyRef = ref<HTMLElement | null>(null)
const editorGridRef = ref<HTMLElement | null>(null)
const workAreaRef = ref<HTMLElement | null>(null)
const tracePanelRef = ref<HTMLElement | null>(null)
const traceDetailRef = ref<HTMLElement | null>(null)
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
  if (event.key === 'Escape' && traceIndex.pinned.value) traceIndex.unselect()
  if (
    desktop.isDesktop.value &&
    event.key === '`' &&
    (event.metaKey || event.ctrlKey)
  ) {
    event.preventDefault()
    openBottomPanel('terminal')
  }
}

function onWindowResize(): void {
  void nextTick(() => {
    clampAgentWidth()
    clampTraceSummaryWidth()
  })
}

onMounted(async () => {
  window.addEventListener('resize', onWindowResize)
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('trace-link-created', handleTraceLinkCreated)
  await nextTick()
  clampAgentWidth()
  clampTraceSummaryWidth()
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

function handleTraceLinkCreated(): void {
  // Refresh trace data when a new link is created
  void trace.loadTraceRows()
}

onUnmounted(() => {
  annotation.resetForProject()
  window.removeEventListener('resize', onWindowResize)
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('trace-link-created', handleTraceLinkCreated)
  stopResize()
  paper.cancelPolling() // stop any in-flight parse poll so it can't hit /projects/NaN/... (422)
})

watch([explorerOpen, explorerWidth, agentOpen, agentWidth], async () => {
  await nextTick()
  clampAgentWidth()
  clampTraceSummaryWidth()
})

watch([bottomPanelOpen, activeBottomPanel], async () => {
  await nextTick()
  clampTraceSummaryWidth()
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
  if (mode === 'traceSummary') {
    // Capture the layout box once so per-move math measures from a stable right edge.
    traceLayoutRect = tracePanelRef.value?.getBoundingClientRect() ?? null
  }
  if (mode === 'tracePreview') {
    traceDetailRect = traceDetailRef.value?.getBoundingClientRect() ?? null
  }
  document.body.style.cursor =
    mode === 'bottom' || mode === 'tracePreview' ? 'row-resize' : 'col-resize'
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
  if (resizeMode.value === 'traceSummary') {
    const layout = traceLayoutRect
    if (!layout) return
    const { min, max } = traceSummaryWidthBounds(layout.width)
    traceSummaryWidth.value = Math.round(
      Math.min(Math.max(layout.right - event.clientX, min), max),
    )
    return
  }
  if (resizeMode.value === 'tracePreview') {
    const detail = traceDetailRect
    if (!detail) return
    const usableHeight = Math.max(detail.height - TRACE_SPLITTER_SIZE, 1)
    const minimumRatio = Math.min(50, (TRACE_SECTION_MIN_HEIGHT / usableHeight) * 100)
    const nextRatio = ((event.clientY - detail.top) / usableHeight) * 100
    traceAgentRatio.value = Math.round(
      Math.min(Math.max(nextRatio, minimumRatio), 100 - minimumRatio) * 10,
    ) / 10
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

function traceSummaryWidthBounds(layoutWidth: number): { min: number; max: number } {
  const available = Math.max(
    TRACE_SUMMARY_NARROW_MIN,
    layoutWidth - TRACE_MATRIX_MIN - TRACE_SPLITTER_SIZE,
  )
  const max = Math.min(TRACE_SUMMARY_MAX, available)
  return { min: Math.min(TRACE_SUMMARY_MIN, max), max }
}

function clampTraceSummaryWidth(): void {
  const layout = tracePanelRef.value?.getBoundingClientRect()
  if (!layout) return
  const { min, max } = traceSummaryWidthBounds(layout.width)
  traceSummaryWidth.value = Math.round(
    Math.min(Math.max(traceSummaryWidth.value, min), max),
  )
}

function stopResize(): void {
  if (resizeMode.value === 'agent') {
    window.localStorage.setItem('tracelab.agent.width', String(agentWidth.value))
  }
  if (resizeMode.value === 'traceSummary') {
    window.localStorage.setItem('tracelab.traceSummary.width', String(traceSummaryWidth.value))
  }
  if (resizeMode.value === 'tracePreview') {
    window.localStorage.setItem(
      'tracelab.tracePreview.agentRatio',
      String(traceAgentRatio.value),
    )
  }
  traceLayoutRect = null
  traceDetailRect = null
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

/** Reveal the matrix alongside the guide, so the new row is visible the moment it lands. */
function startAnnotation(): void {
  if (annotation.active) {
    annotation.cancel()
    return
  }
  openBottomPanel('trace')
  annotation.start()
}

const hasGeneratedTrace = computed(
  () => trace.mode.value === 'agent' || trace.traceLinks.value.length > 0,
)

/**
 * Run the trace agent. When a previous round exists, ask first whether to keep it.
 *
 * Keeping is the default: an unreviewed candidate that the next run rediscovers is upserted by
 * fingerprint, and accepted/rejected decisions are never overwritten — so "保留" costs nothing and
 * lets the new run build on what is already there. "不保留" deletes the previous candidates up
 * front so the matrix shows only this round's output.
 */
async function generateAgentAnalysis(isRerun = false): Promise<void> {
  if (isRerun) {
    let keepPrevious: boolean
    try {
      const action = await ElMessageBox.confirm(
        `当前已有 ${trace.traceRows.value.length} 条追溯结果。重新生成时是否保留这些历史记录？\n`
          + '保留：已接受/已拒绝的判断不会被覆盖，新结果会与旧结果合并。\n'
          + '不保留：先清空未审阅的候选，只显示本轮生成的结果。',
        '重新生成追溯',
        {
          confirmButtonText: '保留历史记录',
          cancelButtonText: '清空后重新生成',
          distinguishCancelAndClose: true,
          type: 'warning',
        },
      )
      keepPrevious = action === 'confirm'
    } catch (action) {
      // ElMessageBox rejects with 'cancel' (the secondary button) or 'close' (X / Esc).
      if (action === 'close') return
      keepPrevious = false
    }
    traceIndex.unselect()
    traceIndex.clearHover()
    if (!keepPrevious) {
      try {
        await trace.clearExisting('proposed')
      } catch {
        return
      }
    }
  }
  await trace.generateSuggestions(isRerun)
  await tensorFlow.loadTensorFlow({ force: true })
}

function toggleDebug(): void {
  const next = !debug.enabled.value
  debug.setEnabled(next)
  if (next) {
    debug.panelOpen.value = true
    debug.info('debug', '调试模式已开启，后续报错会输出完整信息')
  }
  ElMessage.info(next ? '调试模式已开启' : '调试模式已关闭')
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

// Open a file and reveal a line in the code pane. Switching files rebuilds the CodeMirror view
// asynchronously, so CodeEditor queues the reveal when its view is not up yet — this function must
// not try to compensate with extra waiting of its own.
async function jumpToCode(path: string, line: number, endLine?: number): Promise<void> {
  await code.openCodeFile(path)
  await nextTick()
  codeEditorRef.value?.goToLine(line, endLine)
}

async function onGotoDefinition(payload: {
  path: string
  line: number
  column: number
  identifier: string
}): Promise<void> {
  if (!workspace.projectId.value || Number.isNaN(workspace.projectId.value)) return
  try {
    const result = await resolveDefinition(workspace.projectId.value, payload)
    if (result.status === 'resolved' && result.path && result.line_start) {
      await jumpToCode(result.path, result.line_start, result.line_end ?? undefined)
      return
    }
    if (result.status === 'ambiguous') {
      ElMessage.warning(result.reason || '存在多个候选定义，无法自动跳转')
      return
    }
    ElMessage.info(result.reason || '无法跳转到定义')
  } catch {
    ElMessage.error('跳转定义失败')
  }
}

// Clicking a matrix row selects that relation (single source of truth = link id); the
// selectedLinkId watch then drives the one-time dual jump. The drawer is no longer auto-opened.
function onTraceRowSelect(row: TraceRowView): void {
  selectedTraceRow.value = row
  if (row.id) traceIndex.select(row.id, 'paper')
}

// Hovering a matrix row lights up the same relation on both panes (preview only, never jumps).
function hoverTraceRow(row: TraceRowView): void {
  if (row.id) traceIndex.hover(row.id)
}

async function jumpToTracePaper(row: TraceRowView): Promise<void> {
  const evidence = row.evidence.find((item) => item.side === 'paper')
  const link = row.id ? trace.traceLinks.value.find((item) => item.id === row.id) : null
  const paperTargetId = link?.paper_target_id || evidence?.target_id || null
  await nextTick()
  const found = paperReaderRef.value?.scrollToBlock(
    row.paper,
    evidence?.quote || '',
    paperTargetId,
  )
  if (!found) ElMessage.warning('论文精确锚点不可用，已保留当前阅读位置')
}

async function jumpToTraceCode(row: TraceRowView): Promise<void> {
  const evidence = row.evidence.find((item) => item.side === 'code')
  const path = evidence?.path || row.code.split('::', 1)[0]
  if (!path) return
  await jumpToCode(
    path,
    evidence?.match_line_start ?? evidence?.line_start ?? 1,
    evidence?.match_line_end ?? evidence?.line_end ?? undefined,
  )
}

// Selection is the ONLY trigger for a jump, and it fires exactly once per change: selecting a
// relation scrolls the paper to its highlight AND opens the code file at its line. Hover changes
// never reach here, so sweeping the pointer across other relations can no longer move either pane.
watch(
  () => traceIndex.selectedLinkId.value,
  async (linkId) => {
    if (!linkId) return
    const link = trace.traceLinks.value.find((item) => item.id === linkId)
    if (!link) return
    const paperEv = link.evidence.find((item) => item.side === 'paper')
    const codeEv = link.evidence.find((item) => item.side === 'code')
    // Paper side: scroll + highlight the traced block/formula.
    await nextTick()
    const paperBlock = paperEv?.ref || link.paper_block_id
    const paperTargetId = link.paper_target_id || paperEv?.target_id || null
    if (paperBlock) {
      paperReaderRef.value?.scrollToBlock(paperBlock, paperEv?.quote || '', paperTargetId)
    }
    // Code side: open the file and reveal the matched range.
    const codePath = codeEv?.path || link.code_symbol_id.split('::', 1)[0]
    if (codePath) {
      await jumpToCode(
        codePath,
        codeEv?.match_line_start ?? codeEv?.line_start ?? 1,
        codeEv?.match_line_end ?? codeEv?.line_end ?? undefined,
      )
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

async function promptGitHubImport(): Promise<void> {
  let url: string
  try {
    const { value } = await ElMessageBox.prompt(
      '工作台会浅克隆该仓库的默认分支并直接完成静态分析。仅支持 HTTPS 公开仓库。',
      '从 GitHub 导入代码',
      {
        confirmButtonText: '导入',
        cancelButtonText: '取消',
        inputPlaceholder: 'https://github.com/owner/repo',
        inputValue: githubUrl.value,
        inputPattern: /\S+/,
        inputErrorMessage: '请输入仓库地址',
      },
    )
    url = String(value || '').trim()
  } catch {
    return
  }
  if (!url) return
  githubUrl.value = url
  await onGitHubImport()
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

async function onStartConflictAnalysis(): Promise<void> {
  if (code.isEditorDirty.value) {
    const saved = await code.saveEditorBuffer()
    if (!saved) return
  }
  const succeeded = await insights.runAnalysis()
  if (succeeded) ElMessage.success('修改冲突分析完成')
  else if (insights.error.value) ElMessage.error(insights.error.value)
}

async function onCancelConflictAnalysis(): Promise<void> {
  const requested = await insights.cancelAnalysis()
  if (requested) ElMessage.info('正在中止修改冲突分析')
  else if (insights.error.value) ElMessage.error(insights.error.value)
}

async function onConflictOpenPaper(blockId: string, quote: string): Promise<void> {
  await nextTick()
  const found = paperReaderRef.value?.scrollToBlock(blockId, quote, null)
  if (!found) ElMessage.warning('论文证据位置不可用')
}

function onConflictOpenTrace(traceId: string): void {
  openBottomPanel('trace')
  const exists = trace.traceLinks.value.some((item) => item.id === traceId)
  if (exists) traceIndex.select(traceId, 'paper')
  else ElMessage.warning('该追溯关系当前不可用')
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
    const found = paperReaderRef.value?.scrollToBlock(
      action.block_id,
      action.quote || '',
      action.target_id ?? null,
    )
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
  if (tab === 'conflict') void insights.loadInsights()
})
</script>

<style scoped>
.ide-workbench {
  --ide-border: #d8dee6;
  --ide-muted: #6b7785;
  --ide-surface: #ffffff;
  display: grid;
  width: 100%;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  grid-template-rows: 42px minmax(0, 1fr) 23px;
  overflow: hidden;
  overscroll-behavior: none;
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
  flex-shrink: 0;
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
  overscroll-behavior: none;
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
  /* Named areas keep editor/bottom on fixed tracks. Without this, removing the annotation
     guide (v-if) shifts editor-grid into the first `auto` row; tall pane content then pushes
     the bottom panel below overflow:hidden and it looks "unable to open". */
  grid-template-rows: auto minmax(0, 1fr) auto;
  grid-template-areas:
    'guide'
    'editor'
    'bottom';
  overflow: hidden;
  background: #ffffff;
}

.editor-grid {
  grid-area: editor;
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
  grid-area: bottom;
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

.bottom-panel-content.trace-panel-content {
  overflow: hidden;
}

.trace-panel-layout {
  display: grid;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr) 5px var(--trace-summary-width, 220px);
  overflow: hidden;
}

.trace-matrix-pane {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.trace-summary-resize-handle {
  cursor: col-resize;
  background: #e3e8ee;
  transition: background 120ms ease;
}

.trace-summary-resize-handle:hover {
  background: #b7c2ce;
}

.trace-detail-column {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows:
    minmax(72px, var(--trace-agent-share, 1fr))
    5px
    minmax(72px, var(--trace-preview-share, 1fr));
  overflow: hidden;
  border-left: 1px solid var(--ide-border);
  background: #ffffff;
}

.trace-preview-resize-handle {
  z-index: 2;
  cursor: row-resize;
  background: #e3e8ee;
  transition: background 120ms ease;
}

.trace-preview-resize-handle:hover {
  background: #b7c2ce;
}

.trace-preview-pane {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.trace-panel-layout :deep(.trace-matrix) {
  min-width: 760px;
  min-height: 100%;
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
  min-width: 0;
  min-height: 0;
  align-content: start;
  gap: 8px;
  padding: 12px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
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

.trace-summary-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  width: 100%;
}

.trace-summary-actions :deep(.el-button) {
  width: 100%;
  margin: 0;
}

/* When only the primary action is visible, let it span the full row. */
.trace-summary-actions :deep(.el-button:only-child) {
  grid-column: 1 / -1;
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

.bottom-panel-content :deep(.conflict-grid) {
  gap: 8px;
  padding: 9px 10px;
}

.bottom-panel-content :deep(.conflict-card) {
  gap: 7px;
  padding: 10px;
  border-radius: 4px;
}

.bottom-panel-content :deep(.conflict-card h2) {
  font-size: 13px;
}

.bottom-panel-content :deep(.conflict-card p) {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
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
  flex-shrink: 0;
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

/* Discrete agent step + indeterminate running bar (no misleading N/100 denominator). */
.agent-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #55636f;
}

.agent-step-bar {
  position: relative;
  flex: 1;
  height: 4px;
  overflow: hidden;
  border-radius: 3px;
  background: #e2e8ef;
}

.agent-step-bar i {
  position: absolute;
  top: 0;
  left: -40%;
  width: 40%;
  height: 100%;
  border-radius: 3px;
  background: #1f8f78;
  animation: agent-step-slide 1.1s ease-in-out infinite;
}

@keyframes agent-step-slide {
  0% {
    left: -40%;
  }
  100% {
    left: 100%;
  }
}
</style>
