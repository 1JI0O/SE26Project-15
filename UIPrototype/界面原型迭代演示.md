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

# 让论文与代码<br/>在同一工作区中对齐

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

<div class="eyebrow">计划兑现</div>

# 八项计划任务形成了分层成果

<p class="bottom-claim">本轮不以“功能做全”为目标，而以“边界清楚、工程可接续、闭环可演示”为验收基准。</p>

<div class="task-grid">
  <div class="task-item doc"><span>01</span><b>定位与技术选型</b><em>文档草案</em><p>确定独立 Web 工作台主体，预留 IDE / VS Code 扩展入口。</p></div>
  <div class="task-item done"><span>02</span><b>协作环境与工程</b><em>已完成</em><p>Git 规范、接口目录、Vue 3 + TypeScript 与 FastAPI 初始工程。</p></div>
  <div class="task-item doc"><span>03</span><b>需求细化与原型</b><em>文档初步形成</em><p>导入、解析、分析、追溯、管理、报告等模块完成拆分。</p></div>
  <div class="task-item prototype"><span>04</span><b>PDF 解析原型</b><em>初步实现</em><p>提取标题、摘要、章节、段落与页码等论文侧信息。</p></div>
  <div class="task-item prototype"><span>05</span><b>代码导入与分析</b><em>初步实现</em><p>导入 ZIP，扫描文件树、类、函数、导入和模型候选。</p></div>
  <div class="task-item design"><span>06</span><b>数据模型</b><em>设计草案</em><p>围绕项目、片段、追溯、修正记录和报告记录完成拆分。</p></div>
  <div class="task-item done"><span>07</span><b>工作台前端骨架</b><em>已完成</em><p>项目页、双栏阅读、文件树与追溯结果面板均已具备。</p></div>
  <div class="task-item done"><span>08</span><b>联调与展示材料</b><em>已完成</em><p>最小流程可展示，演示文档与页面截图已汇集。</p></div>
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
      <li><b>界面设计：</b>基于 Element Plus 组织页面组件，功能入口清晰、操作路径直接。</li>
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
  <div><b>目前的最小能力实现</b><p>基于 pypdf 提取论文文本和页码；基于 Python AST 产出文件树、类、函数、导入关系与 PyTorch 模型候选。工作区支持代码审阅与修改，论文保持只读。</p></div>
  <div><b>保留的可替换边界</b><p>候选追溯当前以启发式/规则为基础；未来可引入向量检索、LLM 解释、动态运行追踪和流程图交互。它们只通过接口占位，不作为本轮后端算法交付。</p></div>
</div>

---
layout: default
---

<div class="eyebrow">工程协作契约</div>

# 用稳定接口连接可替换的分析能力

<div class="contract-layout">
  <div class="contract-panel">
    <h2>统一 API 作为并行开发边界</h2>
    <div class="contract-row"><code>POST /projects</code><span>创建并管理复现项目</span></div>
    <div class="contract-row"><code>POST /paper · /code</code><span>导入论文 PDF 与代码 ZIP</span></div>
    <div class="contract-row"><code>GET/POST /trace-links</code><span>读取、创建候选追溯关系</span></div>
    <div class="contract-row"><code>GET /workspace/*</code><span>支撑工作台、流程图、冲突与报告占位数据</span></div>
  </div>
  <div class="contract-panel contract-data">
    <h2>数据模型围绕追溯主链收敛</h2>
    <div class="data-chain"><b>项目</b><i>→</i><b>论文文档</b><i>→</i><b>论文片段</b></div>
    <div class="data-chain"><b>项目</b><i>→</i><b>代码仓库</b><i>→</i><b>代码片段</b></div>
    <div class="data-chain emphasis"><b>论文片段</b><i>⇄</i><b>追溯关系</b><i>⇄</i><b>代码片段</b></div>
    <p>人工修正、分析任务和报告记录围绕项目保存，便于后续审阅、复盘与扩展。</p>
  </div>
</div>

---
layout: default
---

<div class="eyebrow">迭代评估报告概要</div>

# 交付物与验收证据已经汇集

<div class="status-columns">
  <section class="done"><h2>可运行的工程</h2><p>前后端初始工程与协作规范</p><p>项目页、工作台与追溯面板</p><p>联调最小流程与展示材料</p></section>
  <section class="progressing"><h2>可接续的设计</h2><p>需求细化、模块拆分与技术选型</p><p>接口契约与数据库初版设计</p><p>论文解析、代码分析最小原型</p></section>
  <section class="next"><h2>可核验的证据</h2><p>运行截图与工作台样例</p><p>接口文档与核心 JSON 格式</p><p>测试记录、评估报告与迭代计划</p></section>
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

<div class="eyebrow">验收矩阵</div>

# 最小闭环已按六类验收项逐段验证

<div class="validation-grid">
  <div><b>项目创建</b><p>项目名称、材料来源等基础信息可保存。</p><span>OK</span></div>
  <div><b>PDF 解析</b><p>标题、摘要、章节、段落、页码可结构化展示。</p><span>OK</span></div>
  <div><b>代码导入</b><p>接收 ZIP、展示过滤后的文件树并识别 Python 文件。</p><span>OK</span></div>
  <div><b>静态分析</b><p>输出类、函数、import、nn.Module 与 forward 等信息。</p><span>OK</span></div>
  <div><b>关系展示</b><p>论文片段、代码片段、理由或占位说明可并列审阅。</p><span>OK</span></div>
  <div><b>前端页面</b><p>项目列表、上传页、双栏页面和追溯面板均可访问。</p><span>OK</span></div>
</div>

<p class="bottom-claim">配套证据：前端生产构建通过；后端 12 项 pytest 测试覆盖核心 API、文件过滤与工作台路径。</p>

---
layout: default
---

<div class="eyebrow">范围变更与风险控制</div>

# 主动收敛范围，避免智能功能阻塞迭代交付

<div class="change-layout">
  <div class="change-now">
    <h2>本轮必须可演示</h2>
    <p>导入论文与代码</p><p>结构化解析与静态分析</p><p>双栏阅读与候选追溯展示</p><p>人工确认/修正的结构与入口</p>
  </div>
  <div class="change-arrow">范围<br/>收敛</div>
  <div class="change-later">
    <h2>后移到后续迭代</h2>
    <p>复杂图文代码对齐与真实张量验证</p><p>完整跨文件调用图与魔改影响分析</p><p>生产级多租户与完整 IDE 替代能力</p><p>大模型解释与向量检索的深度接入</p>
  </div>
</div>

<div class="risk-strip"><b>降级策略：</b>复杂 PDF 先保留页码与附近文本；复杂仓库先定位核心文件；自动匹配不可用时使用规则/关键词与人工链接；接口不稳定时以前端 mock 数据保障演示。</div>

---
layout: default
---

<div class="eyebrow">经验沉淀</div>

# 第一轮迭代留下四条可复用的原则

<div class="lesson-grid">
  <div><span>01</span><b>先控制范围</b><p>先跑通材料导入、解析、展示与追溯，再逐步增加智能能力。</p></div>
  <div><span>02</span><b>文档与接口先行</b><p>项目、片段和追溯关系的 JSON 契约要先固定，减少并行返工。</p></div>
  <div><span>03</span><b>解析分层实现</b><p>先稳定基础结构，再增强公式、图表、算法框与跨文件关系。</p></div>
  <div><span>04</span><b>演示保持可降级</b><p>样例尽早固定，自动分析不稳定时仍能用规则和人工审阅完成闭环。</p></div>
</div>

---
layout: default
---

<div class="eyebrow">下一步与评审请求</div>

# 下一轮先补齐证据链，再提升追溯质量

<div class="next-layout">
  <div class="next-steps">
    <div><span>高</span><b>补齐仓库证据与启动说明</b><p>补充 Git 提交记录、运行样例和启动步骤。负责人：张朴、钱闵浩。</p></div>
    <div><span>高</span><b>固定解析样例与核心 JSON</b><p>补充 PDF/代码分析样例、截图和统一字段契约。负责人：俞冠廷、钱闵浩、秦浩翔。</p></div>
    <div><span>中</span><b>完善原型与报告输出</b><p>补充低保真页面证据、关系确认记录和可导出的复现报告。负责人：张朴、俞冠廷。</p></div>
    <div><span>P2</span><b>增强追溯质量</b><p>在可复核证据基础上逐步接入规则、向量检索、LLM 解释和动态验证。</p></div>
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
