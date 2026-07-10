---
theme: none
title: TraceLab｜迭代 1 展示
info: |
  ## TraceLab 迭代 1 展示
  面向深度学习论文复现的论文—代码双向追溯 Web 工作台
colorSchema: light
fonts:
  sans: 'Songti SC, STSong, SimSun, serif'
  mono: 'JetBrains Mono, Fira Code, monospace'
transition: fade-out
mdc: true
lineNumbers: false
aspectRatio: 16/9
canvasWidth: 1280
duration: 20min
timer: countdown
---

<div class="cover-mark">TraceLab · Iteration 01</div>

# 让论文与代码<br/>在同一条证据链中对齐

<p class="cover-lead">面向深度学习论文复现的论文—代码双向追溯 Web 工作台</p>

<div class="cover-meta">
  <span>第 1 次迭代验收展示</span><span>组号 15</span><span>2026.07.06 — 07.12</span>
</div>
<div class="cover-art"><div></div><div></div><div></div></div>

<!--
开场：TraceLab 不是另一个 PDF 阅读器或 IDE，而是把论文证据、代码证据和人工判断放进同一个项目工作台。
-->

---
layout: default
---

<div class="eyebrow">本次评审</div>

# 三个问题

<p class="bottom-claim">本次迭代主要解决以下三个问题：</p>

<div class="review-grid">
  <section><span>01</span><h2>有价值吗？</h2><p>是否真正减少论文复现中“读论文、找代码、留证据”的反复切换问题？</p></section>
  <section><span>02</span><h2>原型合理吗？</h2><p>是否覆盖项目入口、材料导入、双栏阅读与追溯审阅等核心元素？界面是否友好？设计是否美观？</p></section>
  <section><span>03</span><h2>进度如期吗？</h2><p>计划、评估报告、原型代码与已知风险说明。</p></section>
</div>


---
layout: default
---

<div class="eyebrow">问题与价值</div>

# 复现的难点——论文与实现之间不容易追溯

<div class="value-layout">
  <div class="pain-column">
    <div><b>上下文被切碎</b><p>论文 PDF、代码仓库、IDE 与个人笔记分散，需要反复来回切换，切不容易跟踪。</p></div>
    <div><b>实现定位靠猜测</b><p>论文源码中函数/类的命名未必规范，模型描述、公式、训练脚本与具体类/函数之间缺少稳定的对应关系。</p></div>
    <div><b>结论难以复用</b><p>即使找到了对应位置，也不容易保存、让协作者复核或进行修改。</p></div>
  </div>
  <div class="trace-visual">
    <div class="trace-source">论文片段<br/><small>章节 · 段落 · 页码</small></div>
    <div class="trace-source">代码片段<br/><small>文件 · 类 · 函数</small></div>
    <div class="trace-center">TraceLab<br/><small>候选关系 + 匹配理由 + 人工确认</small></div>
    <div class="trace-result">可跳转、可审阅、可保存的复现记录</div>
  </div>
</div>

---
layout: default
---

<div class="eyebrow">迭代 1 的取舍</div>

# 当前实现——可演示的最小闭环

<div class="flow-row">
  <div><span>01</span><b>创建项目</b><p>统一组织一次论文复现任务</p></div>
  <i>→</i><div><span>02</span><b>导入材料</b><p>论文 PDF 与代码仓库 / ZIP</p></div>
  <i>→</i><div><span>03</span><b>结构化处理</b><p>论文解析与 Python 静态分析</p></div>
  <i>→</i><div><span>04</span><b>展示候选</b><p>论文—代码关系及理由</p></div>
  <i>→</i><div><span>05</span><b>人工审阅</b><p>确认、驳回或修正关系</p></div>
</div>

<div class="scope-grid">
  <div><b>本轮交付重点</b><p>项目管理、代码与论文导入、基础解析/分析、工作台原型与候选关系展示、前端流程图样式。</p></div>
  <div><b>后续迭代的任务</b><p>复杂图文对齐、动态张量验证、流程图生成与交互逻辑、完整魔改影响和风险分析、Agent 接入。</p></div>
</div>

---
layout: default
---

<div class="eyebrow">界面原型演示</div>

# 项目入口页面

<div class="prototype-grid">
  <div class="prototype-copy">
    <h2>以项目为单位复现</h2>
    <ul>
      <li><b>项目列表：</b>以论文复现任务为单位查看状态和进入工作台。</li>
      <li><b>导入入口：</b>论文、代码与后续分析结果在同一项目下归档。</li>
      <li><b>界面设计：</b>组件使用 Ant Design 进行设计，功能清晰，操作直观。</li>
      <li><b>扩展方向：</b>从外部导入项目，项目搜索与批量管理，通过 Arxiv 和 GitHub 直接拉取分析等进阶功能。</li>
    </ul>
  </div>
  <figure><img src="./assets/iter1-project-entry.png" alt="TraceLab 项目入口界面"/><figcaption>入口界面原型截图</figcaption></figure>
</div>

---
layout: default
---

<div class="eyebrow">界面原型演示</div>

# 工作台页面

<div class="prototype-grid workspace-grid">
  <div class="prototype-copy">
    <h2>一屏保留判断所需的上下文</h2>
    <ul>
      <li><b>论文侧：</b>页码、章节与结构化片段，为追溯关系提供可定位锚点。</li>
      <li><b>代码侧：</b>文件树、文件内容和符号信息，支持定位实现位置。</li>
      <li><b>审阅侧：</b>候选关系、理由、置信度与确认操作，避免黑盒链接。</li>
    </ul>
  </div>
  <figure><img src="./assets/iter1-workspace.png" alt="TraceLab 论文代码双栏工作台"/><figcaption>工作台界面原型截图</figcaption></figure>
</div>

---
layout: default
---

<div class="eyebrow">原型覆盖</div>

# 当前可演示实现——工作区基本功能

<div class="coverage-layout">
  <div class="coverage-list">
    <div><span>项目入口</span><p>项目列表、创建/进入项目、状态概览</p></div>
    <div><span>材料导入</span><p>论文 PDF、代码 ZIP / 仓库来源、导入状态</p></div>
    <div><span>论文阅读</span><p>页码、章节、结构化片段与定位锚点</p></div>
    <div><span>代码浏览</span><p>文件树、代码内容、类/函数等符号信息</p></div>
    <div><span>追溯审阅</span><p>候选关系、理由、置信度、确认与修正入口</p></div>
  </div>
  <figure><img src="./assets/iter1-core-panels.png" alt="TraceLab 核心工作台面板"/><figcaption>原型中的核心信息面板</figcaption></figure>
</div>

<div class="bottom-claim">界面设计遵循“先材料、后分析、再审阅”的任务顺序，避免把进阶能力堆到首屏。</div>

---
layout: default
---

<div class="eyebrow">工程基线</div>

# 骨架搭建与最小实现

<div class="architecture-flow">
  <div><b>Web 前端</b><p>Vue 3 · TypeScript<br/>项目页与工作台原型</p></div>
  <i>→</i><div><b>FastAPI 接口</b><p>统一 API · OpenAPI<br/>前后端协作契约</p></div>
  <i>→</i><div><b>解析与分析服务</b><p>PDF 文本/页码提取<br/>Python AST 静态分析</p></div>
  <i>→</i><div><b>项目数据</b><p>SQLite 开发数据库<br/>上传材料与分析结果</p></div>
</div>

<div class="two-evidence">
  <div><b>目前的最小能力实现</b><p>基于PyPdf工具进行简单的论文文档解析，目前仅提取文字，对于论文的切分能力较差；代码文件树、类、函数、导入关系与 PyTorch 模型候选，支持在工作区内对代码文件进行简单的审阅和修改操作。</p></div>
  <div><b>保留的可替换边界</b><p>候选追溯当前以启发式/规则为基础，未来为了确保追溯准确性和鲁棒性会引入 llm 进行辅助；向量检索、LLM 解释和动态运行追踪、流程题生成与交互实现属于后端功能实现，不在本轮完成。</p></div>
</div>

---
layout: default
---

<div class="eyebrow">迭代评估报告概要</div>

# 当前的计划进度

<div class="status-columns">
  <section class="done"><h2>已完成</h2><p>协作环境与前后端初始工程</p><p>Web 工作台前端骨架</p><p>第一次联调与展示材料</p></section>
  <section class="progressing"><h2>已初步形成</h2><p>项目定位与技术选型</p><p>需求细化与原型设计</p><p>PDF 解析、代码静态分析最小原型</p><p>数据库与数据模型设计草案</p></section>
  <section class="next"><h2>问题</h2><p>项目创建和导入不便，需要手动导入</p><p>代码和窗口的宽度较窄，阅读不便</p><p>Vision 文档不够完善，主要聚焦当前阶段的任务，对未来展望不够</p></section>
</div>


---
layout: default
---

<div class="eyebrow">质量与风险</div>

# 先验证“能运行”，再验证“匹配得准”

<div class="quality-layout">
  <div class="quality-proof">
    <h2>本轮已有的验证证据</h2>
    <div><b>前端构建</b><span>Vue 3 + TypeScript 生产构建通过</span></div>
    <div><b>后端测试</b><span>12 项 pytest 测试通过，覆盖核心 API / 工作台路径</span></div>
    <div><b>验收项</b><span>评估报告记录：项目创建、PDF 解析、代码导入与分析、候选关系展示、前端页面均可验证</span></div>
  </div>
  <div class="risk-list">
    <h2>需要持续控制的风险</h2>
    <div><b>复杂 PDF</b><p>优先稳定标题、摘要、章节、段落与页码；公式/图表逐步增强。</p></div>
    <div><b>静态分析边界</b><p>先定位 Python 文件、类、函数、导入和模型候选，不承诺完整跨文件调用图。</p></div>
    <div><b>候选准确性</b><p>以规则匹配和人工确认保底，后续再引入向量检索与 LLM 辅助解释。</p></div>
  </div>
</div>

---
layout: default
---

<div class="eyebrow">下一步与评审请求</div>

# 未来展望

<div class="next-layout">
  <div class="next-steps">
    <div><span>P0</span><b>真实材料闭环</b><p>围绕固定样例，验证导入 → 解析 → 候选 → 确认的完整链路。</p></div>
    <div><span>P1</span><b>可解释与可修正</b><p>补全匹配理由、置信度依据、确认记录和报告输出。</p></div>
    <div><span>P2</span><b>追溯质量增强</b><p>逐步引入规则、向量检索和 LLM 辅助解释，并保留可复核证据。</p></div>
    <div><span>P3</span><b>导入流程简化</b><p>接入 Arxiv Api 和 GitHub，支持根据仓库名自动匹配拉取。</p></div>
  </div>
</div>

---
layout: default
---

<div class="end-slide">
  <div class="eyebrow">TraceLab</div>
  <h1>让论文复现从反复搜索定位<br/>走向易追溯，快定位，可迁移</h1>
  <p>第 1 次迭代：需求澄清与核心原型搭建</p>
  <b>感谢聆听 · 欢迎提问与点评</b>
</div>
