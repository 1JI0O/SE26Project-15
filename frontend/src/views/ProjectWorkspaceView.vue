<template>
  <div class="prototype-page">
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
        <el-tag type="info" effect="plain">论文只读 / 代码可编辑</el-tag>
        <el-button type="primary">导出审阅报告</el-button>
      </div>
    </section>

    <section class="analysis-canvas">
      <article class="paper-panel">
        <header class="panel-title">
          <div>
            <h2>论文原文</h2>
            <p>只读 PDF 页视图，支持段落、公式、图表锚点高亮，不提供内容编辑。</p>
          </div>
          <el-tag type="info" effect="plain">Read-only paper.pdf</el-tag>
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

          <div class="paper-page" aria-label="只读论文预览">
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
            <p>过滤 .gitignore 与 macOS 元数据后的完整仓库树，代码文件可直接编辑。</p>
          </div>
          <el-tag type="success" effect="plain">Editable repo.zip</el-tag>
        </header>

        <div class="code-workbench">
          <aside class="file-tree">
            <div class="tree-head">
              <strong>Repository</strong>
              <span>已忽略 .git、__pycache__、.DS_Store、__MACOSX、构建产物等文件</span>
            </div>

            <div class="tree-list">
              <button
                v-for="node in visibleCodeTree"
                :key="node.path"
                :class="[
                  'file-node',
                  `depth-${node.depth}`,
                  { active: node.path === selectedPath, folder: node.kind === 'folder' },
                ]"
                @click="handleTreeNodeClick(node)"
              >
                <span class="node-name">
                  <span class="node-icon">{{ node.kind === 'folder' ? '▸' : fileIcon(node.name) }}</span>
                  {{ node.name }}
                </span>
                <small>{{ node.meta }}</small>
              </button>
            </div>

            <div class="ignore-summary">
              <strong>过滤规则</strong>
              <span>12 个文件被隐藏，包括 .DS_Store、__MACOSX/、.venv/、dist/。</span>
            </div>
          </aside>

          <div class="editor-shell">
            <div class="editor-tabs">
              <span>{{ selectedFile?.path }}</span>
              <div>
                <el-tag size="small" :type="selectedFile?.statusType" effect="plain">
                  {{ selectedFile?.status }}
                </el-tag>
                <el-tag v-if="isEditorDirty" size="small" type="warning" effect="plain">
                  未保存演示
                </el-tag>
                <el-tag v-else size="small" type="success" effect="plain">已同步</el-tag>
              </div>
            </div>
            <div class="editor-body">
              <aside class="line-gutter">
                <span v-for="line in editableLineNumbers" :key="line">{{ line }}</span>
              </aside>
              <textarea
                v-if="selectedFile"
                :value="editorContent"
                spellcheck="false"
                class="code-editor"
                :aria-label="`${selectedFile.path} 可编辑代码内容`"
                @input="handleEditorInput"
              />
            </div>
            <div class="editor-footer">
              <span>当前符号: {{ selectedFile?.symbol }}</span>
              <span>关联段落: {{ selectedFile?.paperRef }}</span>
              <el-button size="small" type="primary" plain @click="saveEditorBuffer">
                保存到占位接口
              </el-button>
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

      <div v-else-if="activeInsight === 'flow'" class="tensor-flow-layout">
        <article class="tensor-flow-board">
          <header>
            <h2>代码张量流追踪图</h2>
            <p>
              该图由代码仓库中的模型定义、forward 函数和训练入口生成，用于展示 tensor
              在模块之间的流动路径，不表示 PDF/代码处理流程。
            </p>
          </header>
          <div class="tensor-flow-canvas">
            <svg viewBox="0 0 1040 500" role="img" aria-label="代码张量流追踪图">
              <defs>
                <marker
                  id="flow-arrow"
                  markerHeight="10"
                  markerWidth="10"
                  orient="auto"
                  refX="8"
                  refY="5"
                >
                  <path d="M0,0 L10,5 L0,10 Z" fill="#1f8f78" />
                </marker>
              </defs>
              <g class="edge-layer">
                <g v-for="edge in tensorFlowEdges" :key="edge.id">
                  <path
                    :d="edgePath(edge.points)"
                    class="flow-edge"
                    marker-end="url(#flow-arrow)"
                  />
                  <text :x="edge.labelX" :y="edge.labelY" class="edge-label">
                    {{ edge.label }}
                  </text>
                </g>
              </g>
              <g class="node-layer">
                <g
                  v-for="node in tensorFlowNodes"
                  :key="node.id"
                  :class="[
                    'flow-node',
                    node.kind,
                    { active: selectedTensorNode?.id === node.id },
                  ]"
                  role="button"
                  tabindex="0"
                  @click="handleTensorNodeClick(node)"
                  @keydown.enter.prevent="handleTensorNodeClick(node)"
                >
                  <rect :x="node.x" :y="node.y" :width="node.width" :height="node.height" rx="10" />
                  <text :x="node.x + 16" :y="node.y + 26" class="node-kind">{{ node.kindLabel }}</text>
                  <text :x="node.x + 16" :y="node.y + 56" class="node-title">{{ node.title }}</text>
                  <text :x="node.x + 16" :y="node.y + 84" class="node-detail">{{ node.detail }}</text>
                </g>
              </g>
            </svg>
          </div>
        </article>
        <article class="flow-inspector">
          <header>
            <h2>节点定位</h2>
            <el-tag type="info" effect="plain">GET /workspace/tensor-flow</el-tag>
          </header>
          <div v-if="selectedTensorNode" class="inspector-body">
            <strong>{{ selectedTensorNode.title }}</strong>
            <span>{{ selectedTensorNode.kindLabel }} · {{ selectedTensorNode.tensorShape }}</span>
            <p>{{ selectedTensorNode.description }}</p>
            <dl>
              <div>
                <dt>代码位置</dt>
                <dd>{{ selectedTensorNode.sourcePath }}:{{ selectedTensorNode.lineStart }}</dd>
              </div>
              <div>
                <dt>当前文件</dt>
                <dd>{{ selectedPath }}</dd>
              </div>
            </dl>
            <el-button type="primary" plain @click="jumpToTensorNodeCode(selectedTensorNode)">
              跳转到对应代码
            </el-button>
          </div>
          <el-empty v-else description="点击图中节点查看代码定位" />
          <p class="api-note">
            接口仅返回节点、边、代码定位和张量形状占位数据；后续可由 agent 或静态分析工具生成同结构结果。
          </p>
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
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

type TagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'
type TreeNodeKind = 'folder' | 'file'

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

interface CodeTreeNode {
  name: string
  path: string
  kind: TreeNodeKind
  meta: string
  children?: CodeTreeNode[]
}

interface VisibleTreeNode extends CodeTreeNode {
  depth: number
}

interface TensorFlowNode {
  id: string
  kind: 'input' | 'operation' | 'branch' | 'merge' | 'output'
  kindLabel: string
  title: string
  detail: string
  description: string
  tensorShape: string
  sourcePath: string
  lineStart: number
  lineEnd: number
  x: number
  y: number
  width: number
  height: number
}

interface TensorFlowEdge {
  id: string
  source: string
  target: string
  label: string
  labelX: number
  labelY: number
  points: Array<[number, number]>
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
    description: '保留原文页视图，抽取章节、段落、公式、图表和引用锚点；论文区只读展示。',
    status: '已解析',
    tagType: 'success' as TagType,
    action: '重新上传',
  },
  {
    index: '02',
    title: '导入代码 ZIP',
    description: '按 .gitignore 和 macOS 元数据规则过滤，生成 IDE 风格完整代码仓库树。',
    status: '已分析',
    tagType: 'success' as TagType,
    action: '替换代码包',
  },
  {
    index: '03',
    title: '生成代码追踪视图',
    description: '基于代码静态分析输出可交互张量流图、追溯矩阵和魔改冲突占位结果。',
    status: 'UI + 接口占位',
    tagType: 'warning' as TagType,
    action: '',
  },
]

const codeTree: CodeTreeNode[] = [
  {
    name: 'resnet-reproduction',
    path: '',
    kind: 'folder',
    meta: 'root',
    children: [
      {
        name: 'configs',
        path: 'configs',
        kind: 'folder',
        meta: '1 file',
        children: [
          {
            name: 'resnet50.yaml',
            path: 'configs/resnet50.yaml',
            kind: 'file',
            meta: 'config',
          },
        ],
      },
      {
        name: 'data',
        path: 'data',
        kind: 'folder',
        meta: '2 files',
        children: [
          { name: 'imagenet.py', path: 'data/imagenet.py', kind: 'file', meta: 'loader' },
          { name: 'transforms.py', path: 'data/transforms.py', kind: 'file', meta: 'pipeline' },
        ],
      },
      {
        name: 'models',
        path: 'models',
        kind: 'folder',
        meta: '3 files',
        children: [
          { name: '__init__.py', path: 'models/__init__.py', kind: 'file', meta: 'module' },
          { name: 'layers.py', path: 'models/layers.py', kind: 'file', meta: 'ops' },
          { name: 'resnet.py', path: 'models/resnet.py', kind: 'file', meta: '8 links' },
        ],
      },
      { name: 'train.py', path: 'train.py', kind: 'file', meta: 'entry' },
      { name: 'evaluate.py', path: 'evaluate.py', kind: 'file', meta: 'script' },
      { name: 'README.md', path: 'README.md', kind: 'file', meta: 'doc' },
    ],
  },
]

const codeFiles = ref<CodeFile[]>([
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
    path: 'models/layers.py',
    name: 'models/layers.py',
    badge: 'ops',
    status: '张量操作候选',
    statusType: 'primary',
    symbol: 'conv3x3',
    paperRef: 'P3-10',
    linkedLines: [1, 2, 3],
    content: `import torch.nn as nn


def conv3x3(in_planes, out_planes, stride=1):
    return nn.Conv2d(
        in_planes,
        out_planes,
        kernel_size=3,
        stride=stride,
        padding=1,
        bias=False,
    )`,
  },
  {
    path: 'train.py',
    name: 'train.py',
    badge: '3 links',
    status: '训练入口候选',
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
])

const visibleCodeTree = computed<VisibleTreeNode[]>(() => flattenTree(codeTree))
const selectedFile = computed(() => codeFiles.value.find((file) => file.path === selectedPath.value))
const editorContent = ref('')
let editorContentBuffer = ''
const editorLineCount = ref(1)
const isEditorDirty = ref(false)
const editableLineNumbers = computed(() => {
  return Array.from({ length: editorLineCount.value }, (_, index) => index + 1)
})

watch(
  selectedFile,
  (file) => {
    editorContent.value = file?.content ?? ''
    editorContentBuffer = editorContent.value
    editorLineCount.value = countLines(editorContentBuffer)
    isEditorDirty.value = false
  },
  { immediate: true },
)

const insightTabs = [
  { key: 'trace', label: '追溯矩阵' },
  { key: 'flow', label: '张量流流程图' },
  { key: 'conflict', label: '魔改冲突分析' },
  { key: 'report', label: '报告与质量门禁' },
]

const traceRows = [
  { paper: 'P3-12 残差公式', code: 'BasicBlock.forward: out += identity', type: 'implements', confidence: 94 },
  { paper: 'P3-17 projection shortcut', code: 'downsample(x)', type: 'implements', confidence: 88 },
  { paper: 'P5-02 ResNet-50 depth', code: 'configs/resnet50.yaml', type: 'configures', confidence: 79 },
  { paper: 'P6-04 SGD training', code: 'train_one_epoch', type: 'validates', confidence: 73 },
]

const tensorFlowNodes: TensorFlowNode[] = [
  {
    id: 'images',
    kind: 'input',
    kindLabel: 'Input',
    title: 'images',
    detail: 'N x 3 x 224 x 224',
    description: '训练循环中从 dataloader 取出的输入张量。',
    tensorShape: 'N x 3 x 224 x 224',
    sourcePath: 'train.py',
    lineStart: 5,
    lineEnd: 7,
    x: 32,
    y: 72,
    width: 170,
    height: 104,
  },
  {
    id: 'conv1',
    kind: 'operation',
    kindLabel: 'Conv',
    title: 'conv1 + bn1 + relu',
    detail: 'models/resnet.py:20',
    description: 'BasicBlock.forward 中的第一段卷积、归一化和激活。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 20,
    lineEnd: 20,
    x: 286,
    y: 72,
    width: 210,
    height: 104,
  },
  {
    id: 'conv2',
    kind: 'operation',
    kindLabel: 'Conv',
    title: 'conv2 + bn2',
    detail: 'models/resnet.py:21',
    description: '残差分支中的第二段卷积和归一化。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 21,
    lineEnd: 21,
    x: 580,
    y: 72,
    width: 190,
    height: 104,
  },
  {
    id: 'shortcut',
    kind: 'branch',
    kindLabel: 'Branch',
    title: 'identity / downsample',
    detail: 'projection shortcut',
    description: '当维度变化时进入 downsample，否则保留 identity 分支。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 22,
    lineEnd: 23,
    x: 286,
    y: 306,
    width: 300,
    height: 108,
  },
  {
    id: 'add',
    kind: 'merge',
    kindLabel: 'Merge',
    title: 'out += identity',
    detail: 'models/resnet.py:24',
    description: '残差张量与 shortcut 张量相加，对应论文公式 y = F(x, Wi) + x。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 24,
    lineEnd: 24,
    x: 812,
    y: 198,
    width: 180,
    height: 108,
  },
  {
    id: 'logits',
    kind: 'output',
    kindLabel: 'Output',
    title: 'logits',
    detail: 'train.py:7',
    description: '模型前向输出，随后进入 loss 和 backward 训练链路。',
    tensorShape: 'N x classes',
    sourcePath: 'train.py',
    lineStart: 7,
    lineEnd: 8,
    x: 812,
    y: 360,
    width: 180,
    height: 104,
  },
]

const tensorFlowEdges: TensorFlowEdge[] = [
  {
    id: 'images-conv1',
    source: 'images',
    target: 'conv1',
    label: 'input tensor',
    labelX: 220,
    labelY: 116,
    points: [
      [202, 124],
      [286, 124],
    ],
  },
  {
    id: 'conv1-conv2',
    source: 'conv1',
    target: 'conv2',
    label: 'feature tensor',
    labelX: 510,
    labelY: 116,
    points: [
      [496, 124],
      [580, 124],
    ],
  },
  {
    id: 'conv2-add',
    source: 'conv2',
    target: 'add',
    label: 'residual',
    labelX: 784,
    labelY: 150,
    points: [
      [770, 124],
      [792, 124],
      [792, 252],
      [812, 252],
    ],
  },
  {
    id: 'images-shortcut',
    source: 'images',
    target: 'shortcut',
    label: 'identity branch',
    labelX: 88,
    labelY: 268,
    points: [
      [118, 176],
      [118, 360],
      [286, 360],
    ],
  },
  {
    id: 'shortcut-add',
    source: 'shortcut',
    target: 'add',
    label: 'shortcut tensor',
    labelX: 620,
    labelY: 340,
    points: [
      [586, 360],
      [700, 360],
      [700, 278],
      [812, 278],
    ],
  },
  {
    id: 'add-logits',
    source: 'add',
    target: 'logits',
    label: 'block output',
    labelX: 872,
    labelY: 340,
    points: [
      [902, 306],
      [902, 360],
    ],
  },
]

const selectedTensorNode = ref<TensorFlowNode | null>(tensorFlowNodes[0] ?? null)

const conflictItems = [
  {
    level: '高风险',
    type: 'danger' as TagType,
    title: 'stride 下采样与论文描述不一致',
    description: '配置中 stage3 stride 被改为 1，可能改变张量尺寸变化路径和论文基线。',
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
  { value: 'Flow JSON', title: '流程图接口', description: '返回节点、边、张量形状和代码定位。' },
]

function flattenTree(nodes: CodeTreeNode[], depth = 0): VisibleTreeNode[] {
  return nodes.flatMap((node) => [
    { ...node, depth },
    ...(node.children ? flattenTree(node.children, depth + 1) : []),
  ])
}

function handleTreeNodeClick(node: VisibleTreeNode): void {
  if (node.kind === 'file' && codeFiles.value.some((file) => file.path === node.path)) {
    selectedPath.value = node.path
  }
}

function handleEditorInput(event: Event): void {
  const nextContent = (event.target as HTMLTextAreaElement).value
  editorContentBuffer = nextContent
  const nextLineCount = countLines(nextContent)
  if (nextLineCount !== editorLineCount.value) {
    editorLineCount.value = nextLineCount
  }
  if (!isEditorDirty.value) {
    isEditorDirty.value = true
  }
}

function saveEditorBuffer(): void {
  if (!selectedFile.value) return
  selectedFile.value.content = editorContentBuffer
  editorContent.value = editorContentBuffer
  isEditorDirty.value = false
}

function handleTensorNodeClick(node: TensorFlowNode): void {
  selectedTensorNode.value = node
  jumpToTensorNodeCode(node)
}

function jumpToTensorNodeCode(node: TensorFlowNode): void {
  if (codeFiles.value.some((file) => file.path === node.sourcePath)) {
    selectedPath.value = node.sourcePath
  }
}

function edgePath(points: TensorFlowEdge['points']): string {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
}

function countLines(value: string): number {
  if (!value) return 1
  let count = 1
  for (const char of value) {
    if (char === '\n') count += 1
  }
  return count
}

function fileIcon(filename: string): string {
  if (filename.endsWith('.py')) return 'PY'
  if (filename.endsWith('.yaml') || filename.endsWith('.yml')) return 'YML'
  if (filename.endsWith('.md')) return 'MD'
  return 'FILE'
}
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
.conflict-card h2,
.tensor-flow-board h2,
.flow-inspector h2 {
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
.import-card p,
.tensor-flow-board p {
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
.editor-footer,
.flow-inspector header {
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
  grid-template-columns: minmax(460px, 0.92fr) minmax(560px, 1.08fr);
  gap: 16px;
  align-items: stretch;
}

.paper-panel,
.code-panel {
  display: flex;
  min-height: 760px;
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
  min-height: 670px;
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
  grid-template-columns: 280px minmax(0, 1fr);
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
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 10px;
  min-height: 0;
  padding: 12px;
}

.tree-head,
.ignore-summary {
  display: grid;
  gap: 4px;
}

.tree-head span,
.ignore-summary span {
  color: #71808f;
  font-size: 12px;
  line-height: 1.4;
}

.tree-list {
  overflow: auto;
}

.file-node {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 7px 8px;
  border-radius: 6px;
  background: transparent;
  color: #2d3b48;
  text-align: left;
}

.file-node.depth-1 {
  padding-left: 20px;
}

.file-node.depth-2 {
  padding-left: 36px;
}

.file-node.folder {
  color: #536475;
  font-weight: 700;
}

.file-node.active {
  background: #e8f4f1;
  color: #1f8f78;
}

.node-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-icon {
  display: inline-block;
  min-width: 28px;
  color: #1f8f78;
  font-size: 11px;
  font-weight: 700;
}

.file-node small {
  color: #71808f;
}

.ignore-summary {
  padding-top: 10px;
  border-top: 1px solid #dce3ea;
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

.editor-tabs div {
  display: inline-flex;
  gap: 6px;
}

.editor-footer {
  border-top: 1px solid #dce3ea;
  color: #667789;
  font-size: 12px;
}

.editor-body {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
  background: #fbfcfd;
}

.line-gutter {
  overflow: hidden;
  padding: 14px 10px;
  border-right: 1px solid #e4e9ee;
  color: #9aa7b4;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 22px;
  text-align: right;
  user-select: none;
}

.line-gutter span {
  display: block;
}

.code-editor {
  width: 100%;
  height: 100%;
  min-height: 620px;
  resize: none;
  border: 0;
  outline: 0;
  padding: 14px;
  background: #fbfcfd;
  color: #16232f;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 22px;
  white-space: pre;
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
.tensor-flow-layout {
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
.report-card,
.tensor-flow-board,
.flow-inspector {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.trace-matrix,
.assistant-panel,
.tensor-flow-board,
.flow-inspector {
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

.tensor-flow-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(360px, 0.75fr);
  gap: 16px;
}

.tensor-flow-canvas {
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.tensor-flow-canvas svg {
  display: block;
  width: 100%;
  height: auto;
}

.flow-edge {
  fill: none;
  stroke: #1f8f78;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 3;
}

.edge-label {
  fill: #667789;
  font-size: 12px;
  font-weight: 700;
}

.flow-node {
  cursor: pointer;
  outline: none;
}

.flow-node rect {
  fill: #ffffff;
  stroke: #cfd9e3;
  stroke-width: 2;
  transition:
    fill 0.16s ease,
    stroke 0.16s ease;
}

.flow-node:hover rect,
.flow-node.active rect {
  fill: #f0faf7;
  stroke: #1f8f78;
}

.flow-node.input rect,
.flow-node.output rect {
  fill: #f0faf7;
}

.flow-node.branch rect {
  fill: #fff8e6;
}

.flow-node.merge rect {
  fill: #eef3ff;
}

.node-kind {
  fill: #1f8f78;
  font-size: 13px;
  font-weight: 700;
}

.node-title {
  fill: #24313d;
  font-size: 17px;
  font-weight: 700;
}

.node-detail {
  fill: #667789;
  font-size: 13px;
}

.flow-inspector {
  display: grid;
  align-content: start;
  gap: 14px;
}

.inspector-body {
  display: grid;
  gap: 10px;
}

.inspector-body strong,
.inspector-body span {
  display: block;
}

.inspector-body span,
.api-note {
  color: #667789;
  line-height: 1.6;
}

.inspector-body p {
  margin: 0;
  line-height: 1.6;
}

.inspector-body dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.inspector-body dl div {
  display: grid;
  gap: 3px;
  padding: 10px;
  border-radius: 6px;
  background: #f8fafc;
}

.inspector-body dt {
  color: #667789;
  font-size: 12px;
}

.inspector-body dd {
  margin: 0;
  color: #24313d;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
}

.api-note {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  background: #f0faf7;
  font-size: 12px;
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
  .dock-grid,
  .tensor-flow-layout {
    grid-template-columns: 1fr;
  }

  .paper-panel,
  .code-panel {
    min-height: auto;
  }

  .report-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .workspace-head,
  .review-toolbar,
  .step-footer,
  .toolbar-actions,
  .panel-title,
  .editor-tabs,
  .editor-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .import-strip,
  .analysis-canvas,
  .code-workbench,
  .pdf-reader,
  .conflict-grid,
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
