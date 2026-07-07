<template>
  <div class="prototype-page">
    <section class="workspace-head">
      <div>
        <el-button text @click="$router.push('/')">返回项目入口</el-button>
        <div class="title-row">
          <h1>论文代码双向追溯工作台</h1>
          <el-tag effect="plain" type="warning">完整 UI 原型</el-tag>
        </div>
        <p>
          上传论文 PDF 与代码 ZIP 后，在同一视图中阅读论文原文、浏览代码树、编辑代码，并查看追溯关系、
          流程图和魔改冲突分析。
        </p>
      </div>
      <div class="head-meta">
        <span>Project {{ projectIdLabel }}</span>
        <strong>ResNet 论文复现</strong>
      </div>
    </section>

    <section class="import-strip">
      <article v-for="item in importSteps" :key="item.title" class="import-card">
        <div>
          <span class="step-index">{{ item.index }}</span>
          <h2>{{ item.title }}</h2>
          <p>{{ item.description }}</p>
        </div>
        <div class="step-footer">
          <el-tag :type="item.tagType" effect="plain">{{ item.status }}</el-tag>
          <el-button v-if="item.action" type="primary" plain>{{ item.action }}</el-button>
        </div>
      </article>
    </section>

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
        <el-tag type="success" effect="plain">12 条高置信追溯</el-tag>
        <el-tag type="warning" effect="plain">3 处魔改风险</el-tag>
        <el-button type="primary">导出审阅报告</el-button>
      </div>
    </section>

    <section class="analysis-canvas">
      <article class="paper-panel">
        <header class="panel-title">
          <div>
            <h2>论文原文</h2>
            <p>原始 PDF 阅读、段落定位、公式/图表锚点与追溯高亮。</p>
          </div>
          <el-tag type="info" effect="plain">paper.pdf</el-tag>
        </header>

        <div class="pdf-toolbar">
          <span>第 {{ activePaperPage }} / 9 页</span>
          <div>
            <button>缩小</button>
            <button>100%</button>
            <button>放大</button>
          </div>
        </div>

        <div class="pdf-reader">
          <aside class="page-rail">
            <button
              v-for="page in paperPages"
              :key="page"
              :class="{ active: page === activePaperPage }"
              @click="activePaperPage = page"
            >
              <span>Page</span>
              <strong>{{ page }}</strong>
            </button>
          </aside>

          <div class="paper-page">
            <div class="paper-meta">CVPR 2026 Draft - Method Section</div>
            <h3>Deep Residual Learning for Image Recognition</h3>
            <p class="paper-abstract">
              We present a residual learning framework to ease the training of networks that are
              substantially deeper than those used previously. The core idea is to reformulate each
              stacked layer as a residual function with identity shortcuts.
            </p>
            <section class="paper-section">
              <h4>3.1 Residual Building Block</h4>
              <p>
                Formally, a building block is defined as
                <mark>y = F(x, Wi) + x</mark>. The shortcut connection performs identity mapping,
                and its outputs are added to the outputs of the stacked layers.
              </p>
              <p>
                When dimensions increase, the shortcut can either perform identity mapping with
                zero-padding or use a projection shortcut. The implementation should preserve
                <mark>stride, downsample and expansion</mark> semantics.
              </p>
            </section>
            <section class="paper-section two-column-note">
              <div>
                <strong>Algorithm 1</strong>
                <p>Forward pass of the residual block, including projection branch and activation.</p>
              </div>
              <div>
                <strong>Trace anchors</strong>
                <p>P3-12 -> BasicBlock.forward, P3-17 -> downsample branch.</p>
              </div>
            </section>
          </div>
        </div>
      </article>

      <article class="code-panel">
        <header class="panel-title">
          <div>
            <h2>代码工作区</h2>
            <p>代码文件树、编辑页、符号定位和论文段落反向跳转。</p>
          </div>
          <el-tag type="success" effect="plain">repo.zip</el-tag>
        </header>

        <div class="code-workbench">
          <aside class="file-tree">
            <div class="tree-head">
              <strong>文件树</strong>
              <span>已过滤 .gitignore / macOS 元数据</span>
            </div>
            <button
              v-for="file in codeFiles"
              :key="file.path"
              :class="['file-node', { active: file.path === selectedPath }]"
              @click="selectedPath = file.path"
            >
              <span>{{ file.name }}</span>
              <small>{{ file.badge }}</small>
            </button>
          </aside>

          <div class="editor-shell">
            <div class="editor-tabs">
              <span>{{ selectedFile?.path }}</span>
              <el-tag size="small" :type="selectedFile?.statusType" effect="plain">
                {{ selectedFile?.status }}
              </el-tag>
            </div>
            <div class="editor-body">
              <div v-for="line in codeLines" :key="line.number" class="code-line">
                <span class="line-no">{{ line.number }}</span>
                <code :class="{ linked: line.linked }">{{ line.text || ' ' }}</code>
              </div>
            </div>
            <div class="editor-footer">
              <span>当前符号: {{ selectedFile?.symbol }}</span>
              <span>关联段落: {{ selectedFile?.paperRef }}</span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section class="insight-dock">
      <nav class="insight-nav">
        <button
          v-for="tab in insightTabs"
          :key="tab.key"
          :class="{ active: activeInsight === tab.key }"
          @click="activeInsight = tab.key"
        >
          {{ tab.label }}
        </button>
      </nav>

      <div v-if="activeInsight === 'trace'" class="dock-grid">
        <article class="trace-matrix">
          <header>
            <h2>双向追溯矩阵</h2>
            <p>论文段落、公式、图表与代码文件/符号的关联审阅队列。</p>
          </header>
          <div class="trace-row trace-head">
            <span>论文位置</span>
            <span>代码位置</span>
            <span>关系</span>
            <span>置信度</span>
          </div>
          <div v-for="row in traceRows" :key="row.paper" class="trace-row">
            <span>{{ row.paper }}</span>
            <span>{{ row.code }}</span>
            <span>{{ row.type }}</span>
            <el-progress :percentage="row.confidence" />
          </div>
        </article>
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

      <div v-else-if="activeInsight === 'flow'" class="flow-board">
        <article v-for="node in flowNodes" :key="node.title" class="flow-node">
          <span>{{ node.stage }}</span>
          <strong>{{ node.title }}</strong>
          <p>{{ node.description }}</p>
        </article>
      </div>

      <div v-else-if="activeInsight === 'conflict'" class="conflict-grid">
        <article v-for="item in conflictItems" :key="item.title" class="conflict-card">
          <div>
            <el-tag :type="item.type" effect="plain">{{ item.level }}</el-tag>
            <h2>{{ item.title }}</h2>
          </div>
          <p>{{ item.description }}</p>
          <button>查看影响范围</button>
        </article>
      </div>

      <div v-else class="report-layout">
        <article v-for="card in reportCards" :key="card.title" class="report-card">
          <strong>{{ card.value }}</strong>
          <span>{{ card.title }}</span>
          <p>{{ card.description }}</p>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

type TagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'

interface CodeFile {
  path: string
  name: string
  badge: string
  status: string
  statusType: TagType
  symbol: string
  paperRef: string
  linkedLines: number[]
  content: string
}

const route = useRoute()
const projectIdLabel = computed(() => String(route.params.id ?? 'prototype'))

const activePaperPage = ref(3)
const activeMode = ref('审阅模式')
const activeInsight = ref('trace')
const selectedPath = ref('models/resnet.py')

const reviewModes = ['审阅模式', '标注模式', '冲突模式']
const paperPages = [1, 2, 3, 4, 5, 6, 7, 8, 9]

const importSteps = [
  {
    index: '01',
    title: '导入论文 PDF',
    description: '保留原文页视图，抽取章节、段落、公式、图表和引用锚点。',
    status: '已解析',
    tagType: 'success' as TagType,
    action: '重新上传',
  },
  {
    index: '02',
    title: '导入代码 ZIP',
    description: '按 .gitignore 过滤文件，生成目录树、符号表、调用关系和配置索引。',
    status: '已分析',
    tagType: 'success' as TagType,
    action: '替换代码包',
  },
  {
    index: '03',
    title: '生成追溯视图',
    description: '组合规则、向量检索和大模型解释，输出候选关系与审阅理由。',
    status: 'UI 占位',
    tagType: 'warning' as TagType,
    action: '',
  },
]

const codeFiles: CodeFile[] = [
  {
    path: 'models/resnet.py',
    name: 'models/resnet.py',
    badge: '8 links',
    status: '与论文强关联',
    statusType: 'success',
    symbol: 'BasicBlock.forward',
    paperRef: 'P3-12, P3-17',
    linkedLines: [12, 13, 17, 18, 19, 21],
    content: `import torch
import torch.nn as nn


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super().__init__()
        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        identity = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        out += identity
        return self.relu(out)`,
  },
  {
    path: 'train.py',
    name: 'train.py',
    badge: '3 links',
    status: '训练流程候选',
    statusType: 'primary',
    symbol: 'train_one_epoch',
    paperRef: 'P6-04',
    linkedLines: [7, 12, 13],
    content: `def train_one_epoch(model, loader, optimizer, criterion):
    model.train()
    total_loss = 0.0

    for images, labels in loader:
        optimizer.zero_grad()
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    return total_loss / len(loader)`,
  },
  {
    path: 'configs/resnet50.yaml',
    name: 'configs/resnet50.yaml',
    badge: '2 risks',
    status: '配置需复核',
    statusType: 'warning',
    symbol: 'model.depth',
    paperRef: 'P5-02',
    linkedLines: [2, 5, 7],
    content: `model:
  name: resnet50
  num_classes: 1000
training:
  epochs: 90
  batch_size: 256
  base_lr: 0.1
  weight_decay: 0.0001`,
  },
  {
    path: 'README.md',
    name: 'README.md',
    badge: 'doc',
    status: '说明文档',
    statusType: 'info',
    symbol: 'usage',
    paperRef: '无',
    linkedLines: [1],
    content: `# ResNet Reproduction

This repository reproduces residual learning experiments.

- model definitions: models/resnet.py
- training entry: train.py
- default config: configs/resnet50.yaml`,
  },
]

const selectedFile = computed(() => codeFiles.find((file) => file.path === selectedPath.value))
const codeLines = computed(() =>
  (selectedFile.value?.content.split('\n') ?? []).map((text, index) => ({
    number: index + 1,
    text,
    linked: selectedFile.value?.linkedLines.includes(index + 1) ?? false,
  })),
)

const insightTabs = [
  { key: 'trace', label: '追溯矩阵' },
  { key: 'flow', label: '流程图' },
  { key: 'conflict', label: '魔改冲突分析' },
  { key: 'report', label: '报告与质量门禁' },
]

const traceRows = [
  { paper: 'P3-12 残差公式', code: 'BasicBlock.forward: out += identity', type: 'implements', confidence: 94 },
  { paper: 'P3-17 projection shortcut', code: 'downsample(x)', type: 'implements', confidence: 88 },
  { paper: 'P5-02 ResNet-50 depth', code: 'configs/resnet50.yaml', type: 'configures', confidence: 79 },
  { paper: 'P6-04 SGD training', code: 'train_one_epoch', type: 'validates', confidence: 73 },
]

const flowNodes = [
  {
    stage: 'A',
    title: 'PDF 结构化',
    description: '页码、段落、公式、图表、算法框与引用统一生成锚点。',
  },
  {
    stage: 'B',
    title: '代码静态分析',
    description: '文件树、符号、调用链、配置项和实验脚本进入索引。',
  },
  {
    stage: 'C',
    title: '候选追溯生成',
    description: '规则匹配、embedding 检索和 LLM 解释共同生成候选。',
  },
  {
    stage: 'D',
    title: '人工确认与报告',
    description: '确认、驳回、补充证据，最终输出可复审报告。',
  },
]

const conflictItems = [
  {
    level: '高风险',
    type: 'danger' as TagType,
    title: 'stride 下采样与论文描述不一致',
    description: '配置中 stage3 stride 被改为 1，可能改变感受野与论文基线。',
  },
  {
    level: '中风险',
    type: 'warning' as TagType,
    title: '训练 batch size 被缩小',
    description: 'batch size 从 256 改为 64，需要同步调整学习率或记录偏差。',
  },
  {
    level: '待确认',
    type: 'info' as TagType,
    title: 'loss 函数存在本地替换',
    description: '代码使用 label smoothing，论文原文未明确描述该策略。',
  },
]

const reportCards = [
  { value: '86%', title: '追溯覆盖率', description: '方法、模型结构和训练配置已有候选链接。' },
  { value: '12', title: '已确认关系', description: '可进入报告的证据链数量。' },
  { value: '3', title: '冲突项', description: '需要人工解释或回滚的魔改影响。' },
  { value: 'PDF', title: '报告导出', description: '支持摘要、矩阵、流程图和冲突清单。' },
]
</script>

<style scoped>
.prototype-page {
  display: grid;
  gap: 18px;
}

.workspace-head,
.review-toolbar,
.paper-panel,
.code-panel,
.insight-dock,
.import-card {
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

.workspace-head h1,
.panel-title h2,
.trace-matrix h2,
.assistant-panel h2,
.conflict-card h2 {
  margin: 0;
}

.workspace-head h1 {
  font-size: 26px;
}

.workspace-head p,
.panel-title p,
.trace-matrix p,
.assistant-panel p,
.conflict-card p,
.report-card p,
.import-card p {
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

.import-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.import-card {
  display: grid;
  gap: 16px;
  padding: 16px;
}

.step-index {
  color: #1f8f78;
  font-size: 12px;
  font-weight: 700;
}

.import-card h2 {
  margin: 4px 0 0;
  font-size: 17px;
}

.step-footer,
.toolbar-actions,
.review-toolbar,
.panel-title,
.editor-tabs,
.editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.review-toolbar {
  padding: 12px;
}

.toolbar-group {
  display: inline-flex;
  gap: 6px;
  padding: 4px;
  border-radius: 8px;
  background: #eef3f2;
}

.mode-button,
.insight-nav button,
.file-node,
.page-rail button,
.pdf-toolbar button,
.conflict-card button {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.mode-button {
  padding: 8px 12px;
  border-radius: 6px;
  background: transparent;
  color: #536475;
}

.mode-button.active,
.insight-nav button.active {
  background: #1f8f78;
  color: #ffffff;
}

.analysis-canvas {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.12fr);
  gap: 16px;
  align-items: stretch;
}

.paper-panel,
.code-panel {
  display: flex;
  min-height: 700px;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}

.panel-title {
  align-items: flex-start;
}

.pdf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  color: #536475;
  font-size: 13px;
}

.pdf-toolbar div {
  display: inline-flex;
  gap: 6px;
}

.pdf-toolbar button {
  padding: 5px 8px;
  border-radius: 6px;
  background: #ffffff;
  color: #536475;
}

.pdf-reader {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.page-rail {
  display: grid;
  align-content: start;
  gap: 8px;
}

.page-rail button {
  display: grid;
  gap: 2px;
  padding: 8px;
  border: 1px solid #dce3ea;
  border-radius: 6px;
  background: #ffffff;
  color: #667789;
}

.page-rail button.active {
  border-color: #1f8f78;
  background: #e9f6f3;
  color: #1f8f78;
}

.page-rail span {
  font-size: 11px;
}

.paper-page {
  min-height: 620px;
  padding: 42px 48px;
  border: 1px solid #dce3ea;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(36, 49, 61, 0.08);
}

.paper-meta {
  color: #8a97a5;
  font-size: 12px;
  text-transform: uppercase;
}

.paper-page h3 {
  margin: 12px 0 14px;
  color: #16232f;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 26px;
  line-height: 1.25;
}

.paper-abstract,
.paper-section p {
  color: #2d3b48;
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.8;
}

.paper-section h4 {
  margin: 26px 0 8px;
  font-family: Georgia, "Times New Roman", serif;
}

mark {
  border-radius: 4px;
  background: #fff0bf;
  color: inherit;
}

.two-column-note {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 24px;
}

.two-column-note div {
  padding: 12px;
  border: 1px solid #dce3ea;
  border-radius: 6px;
  background: #fbfcfd;
}

.code-workbench {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.file-tree,
.editor-shell {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.file-tree {
  display: grid;
  align-content: start;
  gap: 8px;
  padding: 12px;
}

.tree-head {
  display: grid;
  gap: 4px;
  margin-bottom: 4px;
}

.tree-head span {
  color: #71808f;
  font-size: 12px;
  line-height: 1.4;
}

.file-node {
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 10px;
  border-radius: 6px;
  background: transparent;
  color: #2d3b48;
  text-align: left;
}

.file-node.active {
  background: #e8f4f1;
  color: #1f8f78;
}

.file-node small {
  color: #71808f;
}

.editor-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.editor-tabs,
.editor-footer {
  padding: 10px 12px;
  background: #ffffff;
}

.editor-tabs {
  border-bottom: 1px solid #dce3ea;
}

.editor-footer {
  border-top: 1px solid #dce3ea;
  color: #667789;
  font-size: 12px;
}

.editor-body {
  overflow: auto;
  padding: 12px 0;
  background: #fbfcfd;
}

.code-line {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  min-height: 24px;
  padding: 0 12px;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 24px;
}

.line-no {
  color: #9aa7b4;
  user-select: none;
}

.code-line code {
  white-space: pre;
}

.code-line code.linked {
  display: block;
  margin: 0 -8px;
  padding: 0 8px;
  border-radius: 4px;
  background: #fff0bf;
}

.insight-dock {
  overflow: hidden;
}

.insight-nav {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid #dce3ea;
  background: #fbfcfd;
}

.insight-nav button {
  padding: 9px 12px;
  border-radius: 6px;
  background: #ffffff;
  color: #536475;
}

.dock-grid,
.conflict-grid,
.report-layout,
.flow-board {
  padding: 16px;
}

.dock-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.7fr);
  gap: 16px;
}

.trace-matrix,
.assistant-panel,
.conflict-card,
.report-card {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.trace-matrix,
.assistant-panel {
  padding: 16px;
}

.trace-row {
  display: grid;
  grid-template-columns: 1.2fr 1.4fr 0.7fr 1fr;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid #edf1f4;
}

.trace-head {
  margin-top: 12px;
  color: #667789;
  font-size: 12px;
  font-weight: 700;
}

.suggestion-actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}

.flow-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.flow-node {
  position: relative;
  min-height: 170px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.flow-node span {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  margin-bottom: 12px;
  border-radius: 50%;
  background: #1f8f78;
  color: #ffffff;
  font-weight: 700;
}

.flow-node strong {
  display: block;
  font-size: 16px;
}

.flow-node p {
  color: #667789;
  line-height: 1.6;
}

.conflict-grid,
.report-layout {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.conflict-card,
.report-card {
  display: grid;
  gap: 14px;
  padding: 16px;
}

.conflict-card button {
  justify-self: start;
  padding: 8px 10px;
  border-radius: 6px;
  background: #eef3f2;
  color: #1f8f78;
}

.report-layout {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.report-card strong {
  color: #1f8f78;
  font-size: 28px;
}

.report-card span {
  font-weight: 700;
}

@media (max-width: 1180px) {
  .analysis-canvas,
  .dock-grid {
    grid-template-columns: 1fr;
  }

  .paper-panel,
  .code-panel {
    min-height: auto;
  }

  .flow-board,
  .report-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .workspace-head,
  .review-toolbar,
  .step-footer,
  .toolbar-actions,
  .panel-title {
    align-items: stretch;
    flex-direction: column;
  }

  .import-strip,
  .analysis-canvas,
  .code-workbench,
  .pdf-reader,
  .conflict-grid,
  .flow-board,
  .report-layout,
  .two-column-note {
    grid-template-columns: 1fr;
  }

  .head-meta {
    text-align: left;
  }

  .paper-page {
    padding: 26px 22px;
  }

  .trace-row {
    grid-template-columns: 1fr;
  }
}
</style>
