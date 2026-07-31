# TraceLab 答辩问题整理

> 本文依据仓库**源码与测试**整理，不采信项目内其它说明文档。  
> 覆盖范围：本地后端 `backend/`、云端同步服务 `server/`、前端 `frontend/`、无头核心 `packages/tracelab_core/`、VS Code 扩展 `vscode-extension/`。

---

## 目录

1. [产品一句话与定位](#1-产品一句话与定位)
2. [产品特色与创新点](#2-产品特色与创新点)
3. [追溯流程设计](#3-追溯流程设计)
4. [置信度计算公式设计](#4-置信度计算公式设计)
5. [相较于传统方式的优势](#5-相较于传统方式的优势)
6. [校准与可调参数（所谓“微调”）](#6-校准与可调参数所谓微调)
7. [架构、基于接口的设计与设计模式](#7-架构基于接口的设计与设计模式)
8. [关键技术栈](#8-关键技术栈)
9. [测试与质量保证](#9-测试与质量保证)
10. [其它常见答辩问答](#10-其它常见答辩问答)

---

## 1. 产品一句话与定位

**TraceLab** 是一款**本地优先**的论文—代码双向追溯工作台：把学术论文中的方法描述与开源代码中的符号、行段建立可审阅、带证据的追溯关系，并辅以张量/架构图、Agent 辅助分析、可选云端同步。

它不是单纯的“文档搜索”或“代码搜索”，而是把两侧内容落到**可点击的锚点**（论文块引用句、代码路径与行号引用句），形成可人工接受/拒绝的追溯链路。

---

## 2. 产品特色与创新点

### 2.1 核心特色（答辩可直接讲）

| 特色 | 源码依据（简述） |
|------|------------------|
| 论文↔代码双向追溯 | `TraceLink` 同时保存论文侧与代码侧引用；前端矩阵与双侧阅读器联动高亮 |
| 证据强制、可复核 | Agent 发布候选时必须带双侧 `quote`；服务端按真实内容校验，不匹配则拒绝入库 |
| Agent 为语义决策主体 | 静态关键词重叠管线已退役，不再写入追溯结果；正式候选由 Agent 分析作业产出 |
| 人工在环 | 追溯结果默认 `proposed`；接受/拒绝由人决定。聊天 Agent 的写工具（建链、改状态、改代码等）需确认后才执行 |
| 本地优先 | 本地 FastAPI + SQLite 即可完整工作；项目默认不同步，显式开启云同步才进入 outbox |
| 双运行壳共用前端 | Web（Vite 代理）与 Desktop（Tauri 启动 PyInstaller 后端 sidecar）共用同一套 Vue 界面 |
| 离线可用的检索 | RAG 默认用本地哈希嵌入，不配密钥也能做论文/代码/已审阅案例的语义导航检索 |
| 手工标注模式 | 用户在论文与代码两侧选区后建链，与 Agent 共用锚点规则 |
| 已审阅案例回灌 | 仅把已审核通过的追溯编入 RAG，供后续 Agent 作“先例”参考，不当作证据原文 |
| 冲突分析 | 代码变更后，可对既有追溯跑冲突类 Agent 作业，产出冲突报告 |
| VS Code 平行产品线 | `tracelab_core` CLI + 扩展 Webview，在编辑器内完成解析/分析/追溯/审阅 |

### 2.2 创新点（相对“传统做法”的表述）

1. **从“搜一下类似文本”升级为“带证据的可审阅链路”**  
   传统做法多是关键词或向量检索返回相似段落；本系统要求双侧精确引用，并有状态机（提出→接受/拒绝→因版本变化而过期）。

2. **语义判断交给 Agent，本地索引只做导航**  
   系统提示明确：本地索引不是结论。Agent 必须用工具读真实论文块与源码再发布。

3. **写操作与发布结果分离**  
   - 分析作业的 `publish_trace_candidates`：直接写入 `proposed`，供人审阅。  
   - 对话 Agent 的 `create_trace_link` 等写工具：必须先确认，防止误改。

4. **云端不做重计算**  
   同步服务器只负责账号、Workspace、事件日志与 Blob；不跑 MinerU、AST、LLM、Agent。计算始终在本地（或 VS Code 侧 core）。

5. **可选“深度思考”置信度**  
   项目级开关开启后，服务端用六维加权 + 惩罚项重算置信度，而不是完全听信模型口头分数。

---

## 3. 追溯流程设计

### 3.1 总体链路（主路径）

当前生产路径是 **Agent 分析作业（`kind="trace"`）**，不是静态候选接口。

```
论文解析成功 + 代码分析完成 + LLM 已配置
        │
        ▼
创建/自动创建 AgentAnalysisJob(kind=trace)
        │
        ▼
后台执行 AgentRun（SSE 推送进度）
  STAGE 1 SCOUT  — 浏览论文，找 3～8 个核心贡献
  STAGE 2 MAP    — 在代码中定位模型/损失/训练等
  STAGE 3 DISPATCH — 按区域派生子 Agent 并行取证
  STAGE 4 MERGE  — 合并自检，分批 publish_trace_candidates
        │
        ▼
写入 TraceLink（status=proposed）+ PaperTarget/CodeTarget 锚点
        │
        ▼
人工接受 / 拒绝（可批量）
        │
        ▼
接受后进入 RAG 先例索引；论文或代码版本变化则标记 stale
```

### 3.2 触发方式

1. **自动**：`tracing/coordinator.py` 在论文与代码就绪且 LLM 可用时，可入队 `trace` 作业。  
2. **手动**：前端创建 `POST /projects/{id}/agent/analysis-jobs`，`kind=trace`。  
3. **手工标注**：前端标注状态机选论文区→选代码区→提交；`POST /trace-links`，`source=manual`。  
4. **对话 Agent**：用户对话中可请求建链，但写工具需确认。

### 3.3 作业与步数控制

- 硬上限：trace 类作业约 **100** 步（防无限循环）。  
- 软目标（仅提示模型收尾，非硬停）：  
  \(\text{soft} = 18 + 2\times(\text{公式/算法块数}) + \lfloor\text{块总数}/30\rfloor\)，再夹到 \([28, 64]\)。  
- 子 Agent：区域并行取证（配置项控制并行度与子步数）。

### 3.4 发布与校验

`publish_trace_candidates` 路径大致包括：

1. 用 Pydantic 结构校验候选（双侧证据、关系类型、分数范围）。  
2. 用真实论文块 / 源码行段**重验 quote**（含 occurrence 第几次出现）。  
3. 若开启深度思考，用六维公式重算 `confidence`。  
4. 按指纹去重，写入或更新 `TraceLink`，状态为 `proposed`。  
5. 通过 SSE / 工件快照让前端即时看到结果。

### 3.5 生命周期状态

| 状态 | 含义 |
|------|------|
| `proposed` | Agent 或人工提出，待审 |
| `accepted` | 人工确认有效 |
| `rejected` | 人工判定无效 |
| `stale` | 论文版本或代码 revision 变化后，旧链路过期，不可再当作当前有效审阅对象 |

### 3.6 已退役路径（答辩时要说清楚）

`POST .../trace-links/suggest` 与 `suggest_and_persist` **不再生成并写入**追溯行。  
静态 token 重叠代码仍保留（可作对照或兼容），但正式结果必须以 Agent 为准，避免“没配 LLM 却出现一堆静态假结果”。

### 3.7 答辩问答：追溯流程

**Q1：你们的追溯是怎么做的？一句话。**  
A：Agent 按四阶段读论文、搜代码、分区取证、发布带双侧引用的候选；人再接受或拒绝；版本变了就标过期。

**Q2：为什么不用纯相似度匹配？**  
A：相似度只能说“像”，不能保证“同一公式/同一实现”。我们强制精确 quote 校验，并把本地检索定位为导航工具，语义结论由 Agent 在读完证据后给出。

**Q3：双向追溯体现在哪里？**  
A：链路同时绑定论文块与代码符号/行段；UI 矩阵与双侧阅读器可互跳；手工标注与 Agent 发布共用锚点模型。

**Q4：没有 LLM 时系统还能干什么？**  
A：论文解析、代码 AST、张量图、手工建链、浏览与审阅仍可用；自动 Agent 追溯与需要模型的写操作不可用。静态 suggest 已退役，不会伪装成 Agent 结果。

**Q5：手工标注和 Agent 结果如何统一？**  
A：同一套 `TraceLink` + 锚点推导（如 `path:start-end`）；区别主要在 `source`（`manual` / `agent`）与置信度来源。

---

## 4. 置信度计算公式设计

系统里有多套分数，用途不同。答辩时建议先声明：**当前正式链路以 Agent 发布为主**；静态公式与 static+LLM 融合属于历史/遗留路径。

### 4.1 当前主路径：Agent 直接打分（默认）

模型在发布时给出三个独立分数（均在 \([0,1]\)）：

| 分数 | 含义 |
|------|------|
| `salience` | 论文目标有多重要（目标级） |
| `relevance` | 这段代码在多大程度上实现该目标（边级） |
| `confidence` | 对该判断有多确定 |

默认**不开启**深度思考时：服务端**不重算** `confidence`，按模型给出的值落库（夹到 \([0,1]\)）。  
Prompt 版本：`trace-agent-v2`。

### 4.2 可选主路径：六维深度思考置信度

项目字段 `agent_deep_thinking`（默认关闭）。开启后 Prompt 版本为 `trace-agent-v3`，服务端调用 `compute_trace_confidence()`。

#### 六维及权重（权重和为 1）

| 维度 | 权重 | 直观含义 |
|------|------|----------|
| `change_directness` | 0.20 | 论文到代码映射是否直接、专一 |
| `causal_reachability` | 0.25 | 是否沿调用链读通相关流程 |
| `requirement_support` | 0.20 | 论文是否明确写出该要求/公式 |
| `trace_support` | 0.15 | 是否有可参考的已审先例 |
| `verification_support` | 0.10 | 是否有测试等验证支持 |
| `context_coverage` | 0.10 | 相关上下文文件是否读够 |

默认维度值（模型未填时）：`0.7, 0.6, 0.7, 0.5, 0.5, 0.7`。  
若六维全为默认且无惩罚项 → **退回使用模型原始 `confidence`**（兼容简单情况）。

#### 惩罚项（从候选的 `confidence_penalties` 列表累加）

| 标志 | 扣分 | 含义 |
|------|------|------|
| `paper_association_inferred` | −0.10 | 论文关联是推断的，非明示 |
| `no_call_entry` | −0.20 | 缺少可追踪的调用入口 |
| `alternate_implementation` | −0.20 | 可能存在另一套实现 |
| `config_or_caller_unread` | −0.15 | 配置或调用方未读 |
| `context_truncated` | −0.15 | 上下文被截断 |
| `runtime_condition_unverified` | −0.15 | 运行时条件未核实 |

#### 公式

\[
\text{confidence} = \mathrm{clamp}_{[0,1]}\!\left(\sum_i w_i \cdot d_i + \sum_j p_j\right)
\]

结果保留 4 位小数。

全默认、无惩罚时的加权基数：

\[
0.20\times0.7 + 0.25\times0.6 + 0.20\times0.7 + 0.15\times0.5 + 0.10\times0.5 + 0.10\times0.7 = 0.625
\]

### 4.3 遗留：静态 token 重叠分（不再写库）

对论文块文本与代码符号文本做 token 集合重叠：

\[
\text{overlap}(A,B)=\frac{|T(A)\cap T(B)|}{\max(1,\min(|T(A)|,|T(B)|))}
\]

综合分：

\[
\begin{aligned}
\text{score}=&\,0.35\cdot\text{keyword}
+0.25\cdot\text{comment}
+0.15\cdot\text{call\_support}\\
&+0.15\cdot\text{tensor\_support}
+0.10\cdot\text{path\_prior}
\end{aligned}
\]

阈值：低于 0.20 丢弃；PyTorch 候选保底 0.26；≥0.30（或 PyTorch）倾向 `implements`，否则 `mentions`；取 Top 30。

### 4.4 遗留：静态分与 LLM 解释融合

\[
\text{confidence}=\mathrm{clamp}_{[0,1]}(0.6\cdot c_{\text{static}}+0.4\cdot c_{\text{llm}}-\text{penalty})
\]

不确定性惩罚：`low=0`，`medium=0.05`，`high=0.15`。

### 4.5 RAG 相似度（不是 TraceLink 置信度）

嵌入向量经 L2 归一化后，用**点积**作余弦相似度，只用于检索排序（找相关块/先例），**不写入**追溯链路的 `confidence`。

### 4.6 前端展示

把 `confidence` 乘 100 显示为百分比；颜色大致：≥80 绿、≥50 黄、否则红。

### 4.7 答辩问答：置信度

**Q1：置信度怎么算？**  
A：默认由 Agent 给出 certainty 分。若项目开启深度思考，则服务端用六维加权减惩罚重算；六维全默认且无惩罚时退回模型原分。

**Q2：为什么权重里因果可达最高（0.25）？**  
A：论文方法是否真正落到可执行路径，比表面词相似更关键；鼓励 Agent 读调用链，而不是只匹配名字。

**Q3：为什么有惩罚项而不是只调低维度？**  
A：某些风险是离散事件（例如“调用入口根本没读到”），用显式扣分比含糊压低某一维更可解释，也便于在证据里展示原因。

**Q4：有没有训练/微调神经网络打分模型？**  
A：没有。置信度是规则公式 + Prompt 约束 + 人工审阅；RAG 默认也是哈希嵌入，不是微调过的神经网络。

**Q5：salience / relevance / confidence 为什么拆开？**  
A：重要目标也可能证据不足（高 salience、低 confidence）；次要边也可能很确定。拆开避免一个分数混杂多种含义。

---

## 5. 相较于传统方式的优势

此处“传统方式”指：人工对照论文与代码、IDE 全文搜索、纯向量检索问答、或只做文档生成的工具。

| 维度 | 传统方式常见问题 | TraceLab 做法 |
|------|------------------|---------------|
| 结果形态 | 一段搜索命中，难复用 | 结构化链路 + 双侧锚点 + 状态 |
| 可审计性 | 难回溯“凭什么对上” | 强制 quote，服务端校验 |
| 人机分工 | 要么全自动不可信，要么全手工太慢 | Agent 提出，人审决定 |
| 版本漂移 | 代码一改旧笔记失效无感知 | revision 变化标记 `stale` |
| 隐私与离线 | 常绑定云端大模型服务 | 本地优先；RAG 默认可离线 |
| 领域对象 | 一般文本块 | 论文解析块、AST 符号、张量图节点可联动 |
| 扩展 | 难插工具 | Skills + MCP 注册工具能力 |
| 部署形态 | 单端 Web 或单端插件 | Web / Desktop / VS Code 多壳 |

**答辩可用的对比句：**  
我们不是“再做一个 ChatPDF”，而是把论文方法与代码实现落成**可审阅的追溯资产**，并在本地完成重计算，云端只做可选同步。

---

## 6. 校准与可调参数（所谓“微调”）

仓库中**没有**对开源大模型做参数微调（fine-tuning）的训练代码。答辩若被问“微调了什么”，应诚实回答为：**工程上的 Prompt 版本、权重阈值、检索与作业调度校准**，以及**人工审阅反馈进入先例索引**。

### 6.1 Prompt 与行为校准

| 项 | 说明 |
|----|------|
| `trace-agent-v2` / `v3` | 直接打分 vs 六维打分两套系统提示 |
| 四阶段工作法 | Scout→Map→Dispatch→Merge，约束 Agent 行为顺序 |
| temperature=0 | 降低随机性，利于复现 |
| 先例注入 | 从已审阅链路语义召回少量案例写入提示，作校准参考而非证据 |
| soft_target | 按论文规模提示收尾，硬上限防失控 |

### 6.2 数值阈值与权重

- 静态五分量权重与 0.20 / 0.26 / 0.30 阈值（遗留）  
- static+LLM 的 0.6/0.4 与不确定性惩罚（遗留）  
- 六维权重与六类惩罚（现行可选）  
- 子 Agent 并行度、子步数、LLM 上下文长度等配置项  

### 6.3 嵌入与检索

- 默认 `LocalHashingEmbedder`：字符 n-gram + 词特征哈希，固定维、可离线  
- 可选远程 OpenAI 兼容 `/embeddings`；配置不完整则回退本地  

### 6.4 人工反馈闭环

接受/拒绝会留下审阅事件；接受的链路进入 RAG `trace` 范围，供后续 `recall_trace_cases` 使用——这是**数据侧校准**，不是梯度训练。

---

## 7. 架构、基于接口的设计与设计模式

### 7.1 总体结构

```
┌─────────────────────────────────────────────────────────────┐
│  Vue 3 前端（Web: Vite:5173  /  Desktop: Tauri WebView）      │
│  本地 API 客户端 + 云 API 客户端 + 同步协调                     │
└───────────────┬─────────────────────────────┬───────────────┘
                │ /api/v1                     │ /cloud-api 或云端
                ▼                             ▼
┌───────────────────────────┐    ┌────────────────────────────┐
│ 本地 FastAPI (backend)    │    │ 同步服务器 (server)         │
│ SQLite · 解析·分析·追溯   │    │ PostgreSQL · 账号·Blob·事件 │
│ Agent · RAG · 本地 outbox │    │ 不做 MinerU/AST/LLM/Agent   │
└───────────────────────────┘    └────────────────────────────┘

并行：packages/tracelab_core（CLI）← vscode-extension
```

分层（本地后端）：

`api/routes` → `schemas` → `services` → SQLModel/SQLite + 文件存储  

启动时跑库迁移，并恢复中断的仓库分析与 Agent 作业。

### 7.2 基于接口（Protocol）的可插拔设计

用 `typing.Protocol` 定义契约，工厂或配置选择实现，便于测试注入与运行时切换。

| 接口 | 作用 | 实现示例 |
|------|------|----------|
| `DocumentParser` | PDF/论文解析 | `MinerUParser`（内挂本地或官方客户端）、`StubParser`（测试） |
| `MinerUClientProtocol` / `MinerUTransportProtocol` | MinerU 调用与传输 | 本地服务客户端、官方 API 客户端、urllib 传输 |
| `AgentProvider` | Agent LLM 对话 | OpenAI 兼容实现 |
| `TraceExplanationProvider` | 遗留追溯解释 | OpenAI 兼容 REST |
| `Embedder` | 向量化 | `LocalHashingEmbedder`、`RemoteEmbedder` |
| 前端 `ProjectGateway` | 本地/云端项目访问 | `LocalProjectGateway`、`CloudProjectGateway` |

**切换逻辑举例：**

- MinerU：`create_mineru_parser()` 读集成配置 `mineru_provider` ∈ {local, official}  
- 嵌入：`resolve_embedder()`，远程配置不全则本地哈希  
- LLM：设置里未启用则 Agent/自动追溯不可用，其它本地能力不受影响  

### 7.3 用到的设计模式（结合本项目）

| 模式 | 在本项目中的体现 |
|------|------------------|
| **策略（Strategy）** | 不同 LLM/嵌入/项目网关实现可替换；工具执行器按能力名绑定 |
| **工厂（Factory）** | `create_mineru_parser()`、`resolve_embedder()`、按设置构造 Provider |
| **依赖注入** | FastAPI `Depends(get_session)`；测试可注入 mock Provider；lifespan 注册分析入队函数 |
| **适配器（Adapter）** | OpenAI 兼容端点适配；官方 MinerU API 适配同一 Parser；GitHub URL→克隆导入 |
| **门面（Facade）** | Agent service、RAG service、前端 `synchronizeWorkspace()` 封装多步同步 |
| **观察者 / 事件** | `AgentRunEvent` 落库 + SSE 推送；前端 ReadableStream 消费 |
| **注册表** | `CapabilityRegistry`：内置 Skills + 工具 + MCP 远程工具 |
| **代理（Proxy）** | Vite 开发代理 `/api`；Desktop 经本地后端 `cloud_proxy` 转发云端（处理 WebView 证书问题） |
| **Sidecar** | Tauri 拉起 PyInstaller 打包的 FastAPI，监听本机端口（默认 8765） |
| **内容寻址仓储** | 云端 Blob 按哈希存储去重 |

说明：这里没有上重型 DI 容器，而是 **Protocol + 工厂 + FastAPI Depends** 的轻量接口化。

### 7.4 云同步架构要点

1. 本地业务写入 →（仅 `sync_mode=cloud_enabled`）→ `LocalSyncOutbox`  
2. 前端协调：推送 outbox、拉云端事件、确认 ack；Blob 先上传再引用  
3. 推送前递归剥离密钥、本地绝对路径等禁止字段  
4. 云端 `apply_operation` 做版本与冲突处理；部分类型只追加不覆盖  

### 7.5 答辩问答：架构

**Q1：为什么本地和云端拆成两个服务？**  
A：重计算（解析、AST、LLM）依赖本机资源与用户密钥，应留在本地；云端只做账号与同步，缩小攻击面与部署复杂度，也满足“默认可离线”。

**Q2：基于接口设计的好处？**  
A：同一套业务可换 MinerU 来源、换嵌入、换 LLM、测时换 Stub；前端也可换本地/云项目网关，而不改调用方。

**Q3：Desktop 和 Web 如何共用前端？**  
A：同一 Vue 应用；按是否 Tauri 选择 API 基址。Desktop 用 sidecar 提供 `/api/v1`，云请求走 sidecar 反向代理。

---

## 8. 关键技术栈

| 层 | 技术 |
|----|------|
| 本地后端 | Python 3.11+，FastAPI，SQLModel/SQLAlchemy，Alembic 风格迁移，SQLite，httpx，uvicorn；桌面打包 PyInstaller |
| 云端服务 | FastAPI，PostgreSQL（psycopg），Argon2，JWT，Jinja 管理台，内容寻址 Blob |
| 前端 | Vue 3，Vite，Pinia，Element Plus，CodeMirror 6，pdf.js，axios，SSE（fetch） |
| 桌面壳 | Tauri 2（Rust），系统钥匙串存刷新令牌，可选 PTY 插件 |
| 论文解析 | MinerU（本地服务或官方 API） |
| 代码分析 | Python AST；张量/架构图由分析结果构建 |
| Agent | OpenAI 兼容 Chat Completions；工具调用；SSE；Skills（SKILL.md）；MCP HTTP |
| RAG | 自研分块 + Protocol 嵌入 + SQLite 存向量 |
| VS Code | TypeScript 扩展 + bundled `tracelab_core` CLI |
| 工程 | uv / pnpm；GitHub Actions CI；Ruff；vue-tsc；pytest |

---

## 9. 测试与质量保证

### 9.1 测试分层

| 层 | 位置 | 内容 |
|----|------|------|
| 本地后端单元/集成 | `backend/tests/` | papers、repositories、tracing、agent、rag、sync、settings、迁移、桌面 CORS 等 |
| 发布用补充用例 | `FinalRelease/单元测试代码/` | 代码分析与 RAG 扩展边界，纳入 CI 覆盖率统计 |
| 同步服务器 | `server/tests/` | 集成、契约（不依赖本地 backend 包）、安全门禁；CI 带 PostgreSQL |
| 无头核心 | `packages/tracelab_core/tests/` | 工作区布局、审阅、连通性探测 |
| VS Code 扩展 | `npm test` + 少量 node 测试 | 编译与工具函数 |
| 前端 | CI：`pnpm typecheck` + `pnpm build` | 无前端单元测试进 CI；另有 Playwright 系统用例/证据在 FinalRelease |
| 系统测试材料 | `FinalRelease/` | 用例表、报告、浏览器兼容截图与日志 |

### 9.2 后端测试约定（重要）

`backend/tests/conftest.py`：

- 每测独立 SQLite，避免互相污染  
- **强制关闭 LLM**，测试不访问外网、不依赖本机密钥  
- 后台任务引擎一并替换，并在收尾排空后台任务，降低 flaky  

因此：Agent/追溯相关测试用注入 Provider 或直接测工具与持久化逻辑，而不是打真实模型。

### 9.3 CI 门禁（`.github/workflows/ci.yml`）

五个并行 Job：

1. **local-backend**：`uv sync --frozen` → Ruff → 全量 pytest → **code_analysis 覆盖率 ≥ 90.01%** → **rag 覆盖率 ≥ 90.01%**  
2. **vscode-core**：tracelab_core 的 Ruff + pytest（核心模块有覆盖率门槛）  
3. **sync-server**：Postgres 16 + pytest  
4. **frontend**：Node 22，pnpm 冻结锁安装，typecheck + build  
5. **vscode-extension**：npm ci + npm test  

本地快捷入口：根目录 `make test` / `make lint`。

### 9.4 质量策略归纳

1. **契约测试**：API 行为、退役接口不写库、确认流“确认前无副作用”等。  
2. **安全测试**：同步载荷禁止字段、密钥不回传设置接口、服务端生产门禁与管理台防护。  
3. **恢复测试**：分析作业与 Agent run 中断恢复。  
4. **边界测试**：路径沙箱、quote 校验失败拒绝、锚点近似恢复、RAG 远程配置回退。  
5. **职责隔离测试**：云端 worker 不跑本地分析任务。  

### 9.5 答辩问答：测试

**Q1：如何保证 Agent 相关逻辑可测？**  
A：Provider 可注入；LLM 在测试中关闭；对确认流、发布校验、子 Agent 调度写确定性用例。

**Q2：覆盖率为什么只卡 code_analysis 和 rag？**  
A：这两块是确定性算法核心，适合硬门槛；全仓 Agent 提示与外部服务比例高，全量行覆盖门槛性价比低。全量 pytest 仍每次必跑。

**Q3：前端为什么几乎没有单测？**  
A：CI 用类型检查与生产构建兜底；系统级用 Playwright 与手工/证据材料补充。这是权衡，不是“前端不测”。

---

## 10. 其它常见答辩问答

**Q：项目最大的技术难点是什么？**  
A：把不可靠的模型输出变成**可校验的结构化证据**（quote、行号、occurrence），并在版本变化时维护 stale；同时把 Agent 步数、并行子任务与人工审阅串成稳定产品流程。

**Q：如何防止模型胡编路径和行号？**  
A：工具读真实内容；发布时服务端重验 quote；对不上就拒绝该候选；提示要求记入 unresolved 而非猜测。

**Q：Skills 和 MCP 是做什么的？**  
A：Skills 是内置任务说明书（如追溯分析、架构分析、风险分析）；MCP 把远程工具 schema 拉进能力注册表，扩展 Agent 可调用动作。写操作仍受确认机制约束。

**Q：张量流和追溯什么关系？**  
A：张量/架构图帮助理解模型结构与数据流；静态遗留分里曾用“是否在张量图中”作加分；Agent 也可结合架构工件与图节点 ID 增强证据，但主结论仍靠读源码与论文。

**Q：数据存在哪？**  
A：本地项目在 SQLite + 上传/缓存目录；VS Code 线在工作区 `.tracelab/`；云端在 PostgreSQL + Blob 存储。密钥类集成配置存本地库，接口不回传明文密钥。

**Q：如果同步冲突怎么办？**  
A：云端事件版本检测；前端有冲突相关视图与本地 conflict 记录；禁止字段在推送前剥离，降低把密钥或本机路径同步上去的风险。

**Q：和 VS Code 扩展是什么关系？**  
A：同一产品理念的平行入口：扩展通过 `tracelab_core` CLI 做无头流水线；桌面/Web 走完整 FastAPI。审阅与链路语义对齐，但不是同一个进程。

**Q：创新点请再压缩成三条。**  
A：  
1）证据锚定的论文—代码追溯资产；  
2）Agent 提出 + 人工审阅 + 写操作确认的在环设计；  
3）本地优先、接口可插拔、Web/Desktop/扩展多壳，云端只同步不计算。

---

## 附录 A：关键源码索引（便于现场翻阅）

| 主题 | 路径 |
|------|------|
| 六维置信度 | `backend/app/services/agent/analysis_tools.py`（`compute_trace_confidence`） |
| Trace 作业与 Prompt | `backend/app/services/agent/analysis_jobs.py` |
| 静态重叠分 | `backend/app/services/tracing/static_candidates.py` |
| 退役 suggest | `backend/app/services/tracing/service.py` |
| 追溯 API | `backend/app/api/routes/traces.py` |
| 解析器接口 | `backend/app/services/document_parsers/base.py` |
| 嵌入接口 | `backend/app/services/rag/embeddings.py` |
| Agent 能力注册 | `backend/app/services/agent/capabilities.py` |
| 本地同步 | `backend/app/services/local_sync.py` |
| Desktop sidecar | `frontend/src-tauri/src/lib.rs`，`backend/app/desktop.py` |
| CI | `.github/workflows/ci.yml` |

---

## 附录 B：一页纸口述稿（约 90 秒）

TraceLab 做论文和代码之间的双向追溯。用户导入 PDF 和仓库后，本地完成解析与 AST 分析；配置好兼容 OpenAI 的模型后，Agent 按侦察、映射、分区取证、合并发布四步，产出带双侧精确引用的候选链路。人只负责接受或拒绝；代码或论文版本变了，旧链路会标过期。置信度默认用模型确定性分数；需要更可解释时，可打开深度思考，用六维加权减惩罚由服务端重算。架构上本地算、云端可选同步；解析器、嵌入、LLM 都是接口加工厂，可替换可测。质量上 pytest 强制关网关 LLM，CI 对代码分析和 RAG 卡 90% 覆盖率，并有同步服务与前端构建门禁。

---

## 现场问答补充

### Q：RAG 在这个项目中有什么作用？在哪些环节调用？调用的具体过程是什么？原理是什么？

#### 1. 作用（一句话 + 边界）

RAG 在 TraceLab 里是**语义导航与先例校准层**，不是下结论的裁判。

具体做三件事：

1. **论文侧导航**：按“意思相近”找到可能相关的论文块 id，再交给 `get_paper_block` 精读。  
2. **代码侧导航**：按“要找的计算长什么样”找到候选符号 id，再交给 `get_symbol_source` / `read_source_lines` 精读。  
3. **追溯先例回忆**：从本项目**已人工审阅**（accepted/rejected）的链路里，召回相似案例，给 Agent 校准“什么样的关系站得住/站不住”。

明确不做的事：

- 不直接写入 `TraceLink`，不算置信度结论。  
- 索引失败或关闭时，必须降级为翻页/关键词工具，不能拖垮解析、追溯或对话。  
- 召回的先例**不能当作证据 quote**，也不能直接复用旧 verdict。

#### 2. 在哪些环节调用

**A. 索引构建（写索引）**

| 触发环节 | 做什么 | 源码位置 |
|----------|--------|----------|
| 论文解析成功后 | 重建 `paper` 索引，再可能自动开追溯 | `papers.py` 完成钩子 → `refresh_project_indexes(..., ("paper",))` |
| 代码分析成功后 | 重建 `code` 索引，再可能自动开追溯 | `repositories.py` / `analysis_jobs.py` → `refresh_project_indexes(..., ("code",))` |
| 人工接受/拒绝追溯后 | 把 `trace` 索引标为 pending（下次搜索再建） | `traces.py` → `invalidate(..., "trace")` |
| 云端导入项目后 | 刷新相关索引 | `cloud_import.py` → `refresh_project_indexes` |
| 设置页/API 手动重建 | `POST /projects/{id}/rag/rebuild` | `api/routes/rag.py` |
| Agent 首次搜索而索引未就绪 | `search(..., auto_build=True)` 内联尝试构建 | `rag/service.py` |

**B. 检索使用（读索引）**

| 调用方 | 工具/入口 | 作用域 |
|--------|-----------|--------|
| Trace 分析 Agent（主路径） | `semantic_search_paper` / `semantic_search_code` / `recall_trace_cases` | paper / code / trace |
| Trace 子 Agent | 同上（提示要求先用语义检索定位区域） | 同上 |
| 对话 Agent | 同名三个工具 | 同上 |
| Trace 作业启动时 | `_trace_precedents()` 用论文标题+摘要召回最多 4 条先例注入 system prompt | trace |
| 前端/调试 API | `GET /projects/{id}/rag/search`、`/status` | 任意 scope |
| 设置 UI | 查看/配置 RAG、提示重建 | `IntegrationSettingsDialog.vue` + `rag-api.ts` |

#### 3. 调用具体过程

**建索引过程**

```
源数据就绪（论文解析成功 / 代码分析成功 / 有已审阅链路）
    → 确定 scope 与 source_key
       · paper：content_hash
       · code：{repository_id}:{analysis_revision}
       · trace：已审阅 link 的 blake2b 摘要
    → 若 source_key 未变且 embedder/model 相同 → 直接复用（reused）
    → 否则：分块 → embedder.embed(texts) → 写入 RagChunk（向量 base64 存 SQLite）
    → 更新 RagIndexState（status=ready）
```

分块规则简述：

- **paper**：优先 MinerU 页内 block；过短跳过；过长滑动窗口（2000 字、重叠 200）；嵌入文本前拼 section 路径。  
- **code**：每个符号一块（跳过 import/variable）；拼路径 + 签名/文档/调用 + 源码片段。  
- **trace**：仅 accepted/rejected；拼论文 quote + code_ref + 代码 quote + rationale。

**搜索过程**

```
Agent/API 传入自然语言 query + scope + limit
    → 若索引未 ready 且允许 auto_build → 先 build_index
    → embedder.embed([query]) 得到查询向量
    → 取出该 scope 当前 source_key 下全部 RagChunk
    → 与每条 chunk 向量做余弦相似度（已 L2 归一化 → 点积）
    → 按分数降序；同一 ref 只保留一条
    → 返回 ref + score + 预览文本 + 元数据
    → Agent 必须再用精读工具核对真实内容，才能发布追溯
```

**失败时**

返回 `ok=False` + `reason`（如 `rag_disabled` / `rag_index_empty`），工具层附带 instruction：改用 `list_paper_blocks`、`search_repository_text` 等，不中断作业。

#### 4. 原理

经典 RAG = **检索（Retrieve）+ 生成（Generate）**。本项目里：

- **Retrieve**：把论文块 / 代码符号 / 已审链路变成 chunk，向量化后按相似度取 Top-K。  
- **Generate**：不由 RAG 自己生成答案；把检索结果交给 **Agent（LLM）**，由 Agent 结合精读工具写 rationale、发候选。

向量化两种实现（同一 `Embedder` 接口）：

1. **默认 `LocalHashingEmbedder`（离线）**  
   - 分词：英文词、驼峰拆分、字符 trigram；中文单字与 bigram。  
   - 签名特征哈希：token → blake2b → 维度下标 + 正负号；权重用 \(1+\log(\mathrm{count})\)。  
   - L2 归一化。捕捉的是词法/形态重叠（如 `FocalLoss` ↔ “focal loss”），不是深度语义神经网络。  

2. **可选 `RemoteEmbedder`**  
   - 调 OpenAI 兼容 `/embeddings`；配置不全则回退本地哈希。

相似度：向量已归一化，故 \(\mathrm{cosine}(q,c)=q\cdot c\)。

三作用域上限：paper 4000 / code 6000 / trace 2000 chunks，避免巨大仓库拖垮建索引。

#### 5. 答辩口述压缩版

RAG 是加速器：论文解析和代码分析后自动建索引；追溯 Agent 用语义搜索定位块和符号，用已审阅案例做先例校准；真正结论仍靠读原文和人工审阅。默认本地哈希嵌入，可换远程嵌入；挂了就退回翻页和关键词搜索。

**关键源码**：`backend/app/services/rag/`（`service.py` / `chunking.py` / `embeddings.py`），工具入口在 `analysis_tools.py` 与 `tools.py`，HTTP 在 `api/routes/rag.py`。

### Q：RAG 有没有微调过？如果没有，为什么不微调？

> 口径：**针对检索/嵌入侧**（不是对话大模型的 SFT）。若被问到 LLM 本体，同样没有微调，见产品定位与可插拔 Provider。

#### 结论

**没有。** RAG 未对嵌入模型、重排模型做任何参数微调；仓库无对比学习/LoRA/专用向量模型训练代码或权重产物。

检索只有两路实现（`Embedder` Protocol）：

| 实现 | 性质 |
|------|------|
| 默认 `LocalHashingEmbedder` | 签名特征哈希 + 词法/驼峰/中文 n-gram；**无神经网络、无可训练参数** |
| 可选 `RemoteEmbedder` | 调用用户配置的 OpenAI 兼容 `/embeddings`；本仓库只当客户端，**不改远端权重** |

也没有交叉编码器 rerank、paper↔code 专用嵌入训练流水线。

RAG 侧实际调整的是**工程超参与流程**（仍非微调）：分块规则与窗口、默认维度 512、各 scope chunk 上限、仅索引已审阅 trace、嵌入器切换后使索引失效重建、人工审阅进入先例召回。

#### 为什么不对 RAG 做微调

1. **默认要开箱离线可用**  
   哈希嵌入零密钥、零模型下载、结果可复现。绑微调向量模型会抬高安装体积与设备门槛，和本地优先冲突。

2. **RAG 只导航，不裁决**  
   命中后必须精读 + quote 校验才能发布。架构把正确性放在门禁与人工审阅上；把预算花在“训得更会排”收益有限，且不能替代证据校验。

3. **论文↔代码跨表述，标注贵**  
   自然语言公式 vs 标识符/API，要训好需要大量对齐样本。项目周期内更现实的是：词法哈希保底召回 + Agent 精读 + 已审先例记忆。

4. **嵌入器可插拔，不绑定自家 checkpoint**  
   用户可在设置里换 remote 模型；产品若自带微调权重，授权、版本与更换成本高。

5. **可测性**  
   哈希嵌入确定性好，CI 易测；微调嵌入需固定权重与环境，回归贵。

6. **已有无训练反馈闭环**  
   accept/reject → `trace` 索引 → `recall_trace_cases` / 作业先例注入，是案例记忆，不是改嵌入梯度。

#### 若被追问“以后会不会微调 RAG”

有足够多已审阅 `(论文片段, 正确/错误代码位置)` 后，可做可选的检索重排或领域嵌入；仍应保持默认离线路径，且微调结果不能绕过 quote 校验。

#### 口述压缩版

RAG 没微调。默认本地哈希向量，可选用户自己的远程嵌入。我们调的是分块和索引时机；检索只帮忙找地方，对错靠读原文和人工审阅。

### Q：这个项目用的是什么 RAG？用了向量数据库吗？具体是怎么嵌入成向量的？

#### 1. 用的是什么 RAG

自研的**轻量 RAG 检索层**（不是 LangChain / LlamaIndex 等框架套件），形态可以概括为：

- **三作用域索引**：`paper` / `code` / `trace`  
- **分块 → 嵌入 → 存库 → 余弦 Top-K 检索**  
- **检索结果交给 Agent 继续精读与生成**（Retrieve 在本地服务，Generate 在 LLM Agent）

定位：**Agent 工具型 RAG / 导航型 RAG**，不是“一问一答直接生成最终答案”的问答机器人 RAG。

#### 2. 用了向量数据库吗？

**没有使用独立向量数据库**（无 FAISS / Chroma / Milvus / Qdrant / Pinecone 等）。

向量存在本地 **SQLite** 表 `rag_chunk`：

- 字段 `embedding`：把 float32 向量 **base64 编码成 TEXT** 存放  
- 检索时在 Python 里对当前 scope 的 chunk **暴力算余弦（点积）并排序**  
- 源码注释写明：语料通常仅数千 chunk，精确扫描比重依赖原生向量索引更合适，也利于 PyInstaller 桌面 sidecar 少依赖  

另有 `rag_index_state` 记录每个 `(project, scope)` 的索引是否 ready、用的哪家 embedder、维度等。

#### 3. 具体怎么嵌入成向量

统一走 `Embedder` 接口的 `embed(texts) -> list[list[float]]`，输出均 **L2 归一化**。

**默认：本地签名特征哈希（`LocalHashingEmbedder`）**

1. 截断输入（最长约 8000 字符）  
2. `tokenize`：  
   - 拆 `_` / `.` / `/`，驼峰拆分  
   - 英文小写词；长度>3 时再加字符 trigram（利于部分匹配）  
   - 中文抽单字 + bigram  
3. 对每个 token：`blake2b` → 取维度下标 + 正负号（signed hashing）  
4. 累加权重 \(1 + \log(\mathrm{count})\)（次线性词频，防高频词霸榜）  
5. L2 归一化 → 得到默认 **512 维**向量（可调 64～4096）

这是**词法/形态向量**，不是深度语义神经网络。

**可选：远程嵌入（`RemoteEmbedder`）**

- `POST {base_url}/embeddings`，OpenAI 兼容协议  
- 批量请求，对返回向量再 L2 归一化  
- 设置里选 remote，并配齐 base_url / api_key / model；配不全则回退本地哈希  

**检索打分**：查询与 chunk 都已归一化，相似度 = 点积 = 余弦相似度；`score > 0` 才进入排序，同 `ref` 去重后取 Top-K。

#### 口述压缩版

自研三作用域 RAG，给 Agent 导航用。不用专门向量库，向量 base64 存在 SQLite，内存精确扫描。默认本地哈希嵌入；也可接远程 embeddings API。

