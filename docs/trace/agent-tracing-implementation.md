# Agent 追溯系统实现文档

> 本文描述 TraceLab「论文 ↔ 代码」双向追溯功能**当前的真实实现**(截至 2026-07),而非蓝图。
> 蓝图/设计意图见同目录 [agent-bidirectional-tracing-architecture.md](./agent-bidirectional-tracing-architecture.md);
> 对外契约见 [../contracts/agent.md](../contracts/agent.md)、[../contracts/traces.md](../contracts/traces.md)。
>
> **读者有两类**:
> - 人类维护者 —— 通读第 1~5 节建立心智模型。
> - 后续 Agent —— 先看第 6 节(不变量)与第 7 节(改进方向),再用第 8 节的「下手点」定位要改的文件。所有 `file:line` 均可点击直达;改动前务必按锚点复核代码现状(行号会漂移)。

---

## 1. 一句话概括

追溯不是关键词匹配,也不是本地静态规则,而是**一个 LLM Agent 在单次 Run 内自主读论文、读代码、逐条发布带双侧精确证据的关系**。系统只做三件事保证它可信:

1. **强制证据落地** —— agent 发布的每条关系,论文侧和代码侧的 quote 都必须在指定 `occurrence`(第几次出现)处精确命中,否则该候选被丢弃(见 [§4.4](#44-证据校验与锚定))。
2. **渐进发布 + 单向观测 UI** —— 边分析边渲染,前端选中/悬浮/滚动三条通道彻底解耦,不互相打架(见 [§5](#5-前端实现))。
3. **优雅降级** —— provider 不可用、锚点解析不了时,明确告知而非伪造(见 [§4.6](#46-自动触发协调器)、[§5.3](#53-论文侧--paperreadervue--trace-decorationsts))。

---

## 2. 三层架构与数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│  层 1 · 事实/数据层  (backend)                                         │
│    PaperDocument.pages_json ── inject_block_anchors ──> 带锚点 markdown │
│    CodeRepository.symbols_json / file_tree_json / 原始源码             │
│    PaperTarget / CodeTarget / TraceLink  (规范化落库 + 内容 hash)       │
├─────────────────────────────────────────────────────────────────────┤
│  层 2 · 语义/自动化层  (backend/app/services/agent + tracing)          │
│    coordinator.maybe_start_trace ── 幂等触发 ──> AgentAnalysisJob      │
│    _execute_job 单 Run 四阶段循环 (侦察→制图→取证→归并)                 │
│    工具集(只读代码/论文) + publish_trace_candidates + finish_analysis   │
│    证据校验(anchoring) + 渐进发布(analysis.published SSE)              │
├─────────────────────────────────────────────────────────────────────┤
│  层 3 · 交互层  (frontend/src)                                         │
│    useTrace(SSE 消费+渐进合并) ── traceLinks ──> useTraceIndex(共享索引) │
│    PaperReader(锚点装饰+观测滚动)  CodeEditor(CM6 装饰)  TraceMatrix     │
│    ProjectWorkspaceView(选中→双侧一次跳转 + 固定摘要框)                  │
└─────────────────────────────────────────────────────────────────────┘
```

**端到端时序**(从导入到看见高亮):

1. 用户上传论文 PDF → MinerU 解析 → `pages_json` 落库,解析回调触发 `maybe_start_trace`([papers.py:36-41](../../backend/app/api/routes/papers.py))。
2. 用户导入代码 → 静态分析产出 `symbols_json`/`file_tree_json`/张量图,分析就绪回调也触发 `maybe_start_trace`([repositories.py:201-203](../../backend/app/api/routes/repositories.py))。
3. 协调器确认「论文 succeeded + 代码分析 current + provider 可用」三者齐备 → 幂等创建 `kind="trace"` 的 `AgentAnalysisJob`([coordinator.py:40-70](../../backend/app/services/tracing/coordinator.py))。
4. `_execute_job` 起单 Run 循环,四阶段读证据、分批 `publish_trace_candidates`([analysis_jobs.py:660](../../backend/app/services/agent/analysis_jobs.py))。
5. 每批发布立即校验、落库、发 `analysis.published` SSE([analysis_jobs.py:1046-1056](../../backend/app/services/agent/analysis_jobs.py))。
6. 前端 `useTrace` 消费 SSE,每收到一批就增量拉 `listTraceLinks` 并原地合并 → 矩阵与两侧装饰实时刷新([useTrace.ts:106-145](../../frontend/src/composables/useTrace.ts))。
7. agent 发完所有可辩护候选后调用 `finish_analysis` 显式收尾([analysis_jobs.py:968-973](../../backend/app/services/agent/analysis_jobs.py))。

> **关键点**:张量流图 / 架构图**不在**追溯链路上。它是独立的静态可视化。TF 项目「流程图生成不了」不会中断追溯 —— trace agent 的工具白名单里根本没有图工具(见 [§4.3](#43-工具集))。真正可能拖累追溯质量的是上游 `symbols_json` 是否为空。

---

## 3. 数据模型 (层 1)

三张核心表,定义于 [entities.py](../../backend/app/models/entities.py),建表迁移 [0010_trace_targets.py](../../backend/app/db/migrations/versions/0010_trace_targets.py)(基础 `trace_link` 版本列来自 [0002_trace_agent.py](../../backend/app/db/migrations/versions/0002_trace_agent.py))。

### 3.1 `PaperTarget` ([entities.py:510-548](../../backend/app/models/entities.py))
论文侧被追溯的一个片段。**身份 = `(section_path, quote, occurrence, quote_hash)`**。
- `target_type`:`formula/variable/constraint/algorithm/figure/method_text`
- `block_id`:MinerU 块 id,形如 `p3-b53`
- `quote` + `occurrence` + `char_start/end` + `quote_hash`(规范化 quote 的 sha256)
- `salience`(目标本身有多重要,0~1)、`anchor_status`(锚定降级等级)、`fingerprint`(唯一)

### 3.2 `CodeTarget` ([entities.py:551-588](../../backend/app/models/entities.py))
代码侧被追溯的一个片段。**身份 = `(path, code_quote_hash, occurrence)`**。
- `path` + `symbol_id`(仅当含 `::` 才保留,即真符号而非文件路径)
- `line_start/end` + `column_start/end` + `quote` + `occurrence` + `code_quote_hash`
- `role`:`model_component/loss/tensor_transform/update_rule/constraint/algorithm_step`

### 3.3 `TraceLink` ([entities.py:116-182](../../backend/app/models/entities.py))
一条关系(边)。**身份 = `trace_id` + `fingerprint`**(唯一约束)。
- 双侧引用:`paper_target_id` / `code_target_id`(FK),兼容字段 `paper_ref`/`code_ref` 仍存 block_id/symbol_id
- **三个独立分数**(务必分清,见术语表):`relevance`(边:代码实现了多少)、`confidence`≈`llm_confidence`(边:确定性)、目标上的 `salience`
- `relation_type`(`implements` 等)、`rationale`、`evidence_json`(内嵌两侧 occurrence/char_range/quote_hash/salience)
- `status`:`proposed`/`accepted`/`rejected`/`stale`,默认 `proposed`
- `source`:agent 写入的为 `"agent"`,`static_confidence=0`、`llm_confidence=confidence`

> **落库不变量**:`_persist_trace_links` 会**跳过已 `accepted`/`rejected` 的 link**([analysis_jobs.py:416-418](../../backend/app/services/agent/analysis_jobs.py)),保护人工决策不被重跑覆盖。只有带完整 `paper_anchor`+`code_anchor` 的候选才落库([:401-403](../../backend/app/services/agent/analysis_jobs.py))。

---

## 4. 后端实现 (层 2)

主文件 [analysis_jobs.py](../../backend/app/services/agent/analysis_jobs.py)(循环、落库、终止)与 [analysis_tools.py](../../backend/app/services/agent/analysis_tools.py)(工具 schema、证据校验)。

### 4.0 Agent 是怎么找重点、又怎么对应上的(四阶段工作流)

> 先读这一节,建立「agent 脑子里在干什么」的直觉;后面的 4.1~4.7 是支撑它的机制。

**核心心智模型**:我们**没有**写任何「论文出现 loss 就去找 loss 函数」这类规则。真正干活的是一个 LLM agent,它像一个**读论文的工程师**——先通读论文挑出这篇文章真正的贡献,再翻代码库找到实现这些贡献的地方,然后**逐条论证**「论文要求的这个计算,这段代码是不是真的做了」。这套流程被固化成 system prompt 里的**四个阶段**,agent 在**同一次 Run**里顺序走完([_system_prompt](../../backend/app/services/agent/analysis_jobs.py#L183-L225))。

#### 阶段 1 · SCOUT —— 从论文里挑出「重点」

agent 先用 `list_paper_blocks` / `get_paper_block` 读**摘要和章节结构**(不是全文硬啃),干三件事:

1. 提炼出 **3~8 个核心贡献 / 方法组件**,以及它们分别落在论文哪一节。
2. 把方法章节里的**公式、算法/伪代码、关键图**标记为 **must-inspect**(「必须去代码里找到对应实现」的清单)。
3. **主动排除**背景介绍、相关工作、实验/结果表格 —— 这些不参与追溯。

> 所以「论文重点」= agent 自己判断出的 must-inspect 集合,不是关键词命中,也不是所有段落。一篇论文可能几十个块,但真正进入追溯的往往只有十几个核心目标。这也是为什么系统强调「**少而精**,别堆满高亮」。

#### 阶段 2 · MAP —— 给代码库画一张「职责地图」

agent 用 `list_repository_files` / `list_code_symbols` / `get_symbol_source` **快速扫**一遍代码,定位几类关键位置:**模型定义、损失函数、张量变换、主训练/推理循环、约束、更新规则**在哪些文件哪些符号里。

> 注意:这一步的产物只是**导航用的地图,不是结论**。prompt 明确要求「treat this as navigation only」—— 找到「疑似 loss 的函数」不等于「它就实现了论文那个 loss」,还得靠阶段 3 验证。这一步也是 `symbols_json` 好坏直接影响追溯质量的地方(见 [§7.9](#79-张量图与追溯的关系澄清项非-bug))。

#### 阶段 3 · REGION EVIDENCE —— 把两边真正「对上」

这是**对应关系诞生**的阶段,也是最关键的一步。对阶段 1 挑出的**每一个论文重点**,agent 做三件事:

1. **把论文语义翻译成「代码搜索意图」** —— 不搜论文里的词,而是想清楚「要实现这个,代码里必然会发生什么计算」,再据此去读真实源码(`read_source_lines` / `get_symbol_source` / `search_repository_text`)。
2. **反证检查(counter-check)** —— 同名的符号是不是只是个配置项、包装器、或测试?prompt 明确要求排除这些假阳性,**只有当「真实计算确实发生」时才保留这条关系**。
3. **允许一对多** —— 一个论文重点如果分散实现在多处,就产出多条候选(后续按 relevance 排序)。

> 「对应」的判据是**语义论证**,不是文字重叠。prompt 里有一条硬规则:`never let keyword overlap be the verdict`(绝不把关键词重合当作定论)。举个具体的:论文给了一个 hybrid force 损失公式,agent 不会因为代码里有个函数叫 `loss` 就连线;它会去读那个函数体,确认里面真的按那个公式组合了力项和位姿项,才发布这条 `implements` 关系,并把公式文本和代码行分别作为双侧证据。

#### 阶段 4 · MERGE & SELF-CHECK —— 收敛与自校

发布前的最后一道:

- **只留真正重要的**:核心贡献、must-inspect 的公式/算法、定义性的变量/约束,或有直接重要实现的东西;相邻的同义目标**合并**,不叠加重叠高亮。
- **每条关系打三个独立分数**:`salience`(这个目标本身多重要)、`relevance`(代码实现了多少)、`confidence`(有多确定)——三者不可混用(见术语表)。
- **设对 occurrence**:同一句 quote 在块内/文件内重复时,必须标明是第几次出现,否则锚不到。
- **闭环自查**:每个 must-inspect 目标要么被 linked,要么被明确列进 `unresolved`(附上「我搜过哪些代码区域但没找到」),不允许悄无声息地漏掉。

#### 这四阶段和后面机制的关系

| 阶段 | agent 在做什么 | 靠哪些机制兜底(见下文) |
|---|---|---|
| SCOUT | 挑论文重点(must-inspect) | 论文块工具 §4.3 |
| MAP | 画代码职责地图 | 代码只读工具 §4.3、读结果缓存 |
| REGION EVIDENCE | 逐条论证对应关系 | 发布即校验 §4.4(occurrence+quote_hash) |
| MERGE & SELF-CHECK | 收敛、打分、闭环 | 软目标/收尾 nudge §4.2、渐进发布 §4.7 |

> 一句话:**四阶段决定「找什么、怎么对」,机制层(4.1~4.7)只负责让 agent 的每一步不越界、每条证据能落地、跑不飞也停得下来。**

### 4.1 Agent 分析循环

入口 `_execute_job(job_id)`([:660](../../backend/app/services/agent/analysis_jobs.py)),单 Run、单线程(`ThreadPoolExecutor(max_workers=2)` + `_submitted` 去重,[:33-35](../../backend/app/services/agent/analysis_jobs.py))。已 `succeeded` 的 job 直接 no-op;revision 漂移则 `repository_revision_changed` 失败。

主循环 `for step_number in range(1, budget + 1)`([:765](../../backend/app/services/agent/analysis_jobs.py)),每步:
1. 发 `analysis.progress`(带 `step`)。
2. 调 `provider.next_step(...)`。可重试错误(`llm_invalid_json`/`llm_rate_limited`/`llm_timeout` 等,`_RETRYABLE` [:731-738](../../backend/app/services/agent/analysis_jobs.py))最多重试 6 次,补一条「重发严格 JSON」的 runtime 消息后 `continue`。
3. 记录 model step 到 `run.trace_json`,重算 `run.step_count`。
4. `action=="final"`(想用自然语言收尾)被拒:补 `analysis_output_incomplete` 反馈,要求它必须调用发布工具([:812-823](../../backend/app/services/agent/analysis_jobs.py))。

### 4.2 预算:软目标 vs 硬上限

**关键设计:步数没有固定值,靠 agent 自己 `finish_analysis` 收尾。** 步数上只有两个界:

- **硬上限**(纯安全兜底):`budget = 48 if kind=="architecture" else 100`([:742](../../backend/app/services/agent/analysis_jobs.py))。
- **软目标**(仅提醒收敛,trace 专属),由论文启发式推断 `_trace_soft_target`([:582-601](../../backend/app/services/agent/analysis_jobs.py)):
  ```python
  soft = 18 + 2 * n_formula + len(blocks) // 30
  return max(28, min(soft, 64))   # n_formula = equation/equation_interline/algorithm 块数
  ```
  写进 system prompt(「aim to finish within about N tool steps」),并驱动两次 nudge:
  - **收敛提醒**(`step >= soft_target` 时一次):`soft_target_reached` —— 把没确认的放 unresolved、别再读了([:862-879](../../backend/app/services/agent/analysis_jobs.py))。
  - **收尾催促**(发布后仍超软目标):`wrap_up` —— 立刻 `finish_analysis`([:1057-1072](../../backend/app/services/agent/analysis_jobs.py))。

### 4.3 工具集

`tool_definitions(kind)` 用**白名单**过滤,architecture 与 trace 各一套([analysis_tools.py:293-330](../../backend/app/services/agent/analysis_tools.py)):

| 工具 | trace | architecture | 读取的数据源 |
|---|:-:|:-:|---|
| `list_repository_files` | ✅ | ✅ | `repository.file_tree_json` |
| `search_repository_text` | ✅ | ✅ | **原始源码**(遍历最多 500 文件,大小写折叠子串匹配) |
| `list_code_symbols` | ✅ | ✅ | `repository.symbols_json` |
| `get_symbol_source` | ✅ | ✅ | `symbols_json` 定位 + **原始源码**行区间 |
| `get_symbol_calls` | ✅ | ✅ | `repository.analysis_json["calls"]` |
| `read_source_lines` | ✅ | ✅ | **原始源码**(≤400 行窗口) |
| `list_paper_blocks` | ✅ | — | `_paper_blocks`(源自 `pages_json`) |
| `get_paper_block` | ✅ | — | 单个论文块 |
| `get_analysis_artifact` | ✅ | ✅ | 当前 revision 的 `AgentAnalysisArtifact` |
| `publish_trace_candidates` | ✅ | — | 发布(见 §4.4) |
| `finish_analysis` | ✅ | — | 显式收尾 |
| `publish_architecture_graph` | — | ✅ | 发布架构图 |

> **张量图/架构图工具**(`get_architecture`/`get_graph_node`/`get_tensor_flow`)只在**交互式对话** Agent([tools.py](../../backend/app/services/agent/tools.py))里可用,**不在 trace 白名单内**。这就是「TF 流程图生成失败不干扰追溯」的根本原因。

**读结果缓存**:`_READ_TOOLS`([:746-756](../../backend/app/services/agent/analysis_jobs.py))里的工具,以 `工具名|规范化参数` 为 key 缓存([:826-830](../../backend/app/services/agent/analysis_jobs.py));重复读命中缓存并附「别再读了,去发布」提示,避免烧步数([:831-861](../../backend/app/services/agent/analysis_jobs.py))。

### 4.4 证据校验与锚定

发布走 `_execute_publish_trace`([analysis_tools.py:609-674](../../backend/app/services/agent/analysis_tools.py)),两段**非致命丢弃**:
1. **schema 校验**:逐候选 `TraceCandidate.model_validate`,坏的丢弃。
2. **证据校验** `_validate_traces`([:546-582](../../backend/app/services/agent/analysis_tools.py)):**丢弃单条无效候选而非整批失败**;只有「有候选但全军覆没」才 `all_candidates_invalid`。空 payload 一律拒绝(`empty_publish`)。

单条校验 `_validate_one_trace`([:517-543](../../backend/app/services/agent/analysis_tools.py)):
- 论文侧:`resolve_anchor(block_text, quote, occurrence)` 在指定 occurrence 处定位,失败 → `paper_evidence_quote_invalid`。
- 代码侧:先在声明的行区间内锚,失败则**对整个文件重锚并用真实命中修正行号**([:472-482](../../backend/app/services/agent/analysis_tools.py)),算出 char 偏移与行列。
  - 降级到 `normalized` / `approximate` 时没有 char 偏移,此时行号仍只是模型的**未经核实的声明**。`locate_approximate_span`([anchoring.py](../../backend/app/services/tracing/anchoring.py))按字母数字签名在文件里定位 quote,把 `match_line_start` / `match_line_end` 收敛到**真正命中的行**;声明区间只有在包含该命中时才作为上下文保留,否则整体替换。这样 UI 上的 `:行号` 与代码栏装饰指向的一定是核实过的位置。

锚定核心在 [anchoring.py](../../backend/app/services/agent/anchoring.py):`resolve_anchor` 有**降级等级** `exact → normalized → approximate`,再不行才 `AnchorError`;`quote_hash` = 规范化 quote 的 sha256。这套 occurrence + hash 机制就是「不许伪造证据」的技术底座。

发布 schema(`trace-agent-v2`):`TracePaperEvidence`([:150-161](../../backend/app/services/agent/analysis_tools.py))、`TraceCodeEvidence`([:164-178](../../backend/app/services/agent/analysis_tools.py))、`TraceCandidate`([:181-204](../../backend/app/services/agent/analysis_tools.py),含三分数、`rationale` 必填、`uncertainty_level`)、`TracePayload`([:213-217](../../backend/app/services/agent/analysis_tools.py),`candidates` + `unresolved`)。

### 4.5 论文 markdown 锚点注入

`inject_block_anchors(markdown, pages)`([paper_markdown.py:124-193](../../backend/app/services/paper_markdown.py))把 `<span id="paper-block-{safe}" data-paper-block-id="{block_id}"></span>` 注入渲染 markdown,供前端定位。

- **模糊前缀匹配**([:150-166](../../backend/app/services/paper_markdown.py)):把块文本归一化后,用逐渐变短的前缀 `[全文, :120, :60, :40, :24]` 去正文找,`< 12` 字停;处理内联 `$…$` 导致全串对不上的情况。
- **`$$` 数学块安全放置**:`_math_safe_line_start`([:101-121](../../backend/app/services/paper_markdown.py))把 span 放到公式**上方独立行**,绝不落进 `$$` 定界符内(否则 KaTeX 会把 span 当公式吞掉 —— 这是迭代 3 修过的坑)。
- 每块记 `render_anchor` + `anchor_resolved`(True 当且仅当某前缀匹配成功)。

> **锚点覆盖是当前最大的数据层短板**:前缀匹配失败 → `anchor_resolved=False` → **不注入 span** → 前端查不到 `[data-paper-block-id]`。这就是「p3-b53 论文侧无高亮」的根因。前端已做 quote 兜底 + 「论文锚点不可用」提示(见 [§5.3](#53-论文侧--paperreadervue--trace-decorationsts)),但根治要改后端匹配策略(见 [§7](#7-改进方向))。

### 4.6 自动触发协调器

`maybe_start_trace(project_id)`([coordinator.py:40-70](../../backend/app/services/tracing/coordinator.py))三重门:论文 `parse_status=="succeeded"` + 代码 `analysis_is_current` + `_provider_ready`。齐备则幂等建 job,**永不抛异常**(try/except 兜底返回 `[]`)。

**自动只建 `trace`,不建 `architecture`**([:62-65](../../backend/app/services/tracing/coordinator.py))。原因:流程图由本地静态分析生成、不消费架构 artifact;架构 agent 成本高、小模型上不稳定,不该阻塞双向追溯交付。

四个触发钩子都调 `maybe_start_trace`:论文解析完成、代码分析就绪、代码上传、provider 在设置里被启用。幂等靠 `create_analysis_job` 的 fingerprint([analysis_jobs.py:75-88](../../backend/app/services/agent/analysis_jobs.py)):非 `force` 且同指纹 job 处于 `queued|running|validating|succeeded` 则复用;`force` 用 uuid 加盐重跑。

### 4.7 事件与 SSE

`RunEventEmitter`([run_events.py:24-70](../../backend/app/services/agent/run_events.py))为每个 run 维护单调 `sequence` 写库。循环产生的事件:`analysis.started`/`progress`/`tool.started`/`tool.completed`/`tool.failed`/`validating`/**`published`**/`completed`/`failed` + `run.completed`。

流式路由 [agent.py](../../backend/app/api/routes/agent.py):
- job 级 `GET /analysis-jobs/{job_id}/events`([:151-192](../../backend/app/api/routes/agent.py)),0.4s 轮询,job 终态即结束。
- run 级 `GET /runs/{run_id}/events`([:328-370](../../backend/app/api/routes/agent.py))。

**渐进发布契约**:`analysis.published` 带 `new_links`/`total_links`/`artifact_id`/`code_revision`。同一 run **复用一个 artifact**:首发建 artifact,后续 `_append_trace_links` 追加([analysis_jobs.py:562-579](../../backend/app/services/agent/analysis_jobs.py)),links 按内容指纹幂等累加、不互相清除。

---

## 5. 前端实现 (层 3)

### 5.1 数据加载 —— `useTrace.ts`

[useTrace.ts](../../frontend/src/composables/useTrace.ts) 持有两个 ref:`traceRows`(矩阵视图行)与 `traceLinks`(喂给索引的原始 link),分离。

- `runAnalysis(kind, force)`([:123-157](../../frontend/src/composables/useTrace.ts)):建 job → `streamAgentAnalysisJob` 消费 SSE。收到 `analysis.published` 就 `mergePublishedLinks()`([:142-145](../../frontend/src/composables/useTrace.ts))。
- `mergePublishedLinks`([:106-121](../../frontend/src/composables/useTrace.ts)):`mergingLinks` 布尔锁防止 SSE 重入竞态;重新拉 `listTraceLinks`,原地换 `traceLinks`/`traceRows`,置 `mode='agent'`。
- `generateSuggestions(force)`([:159-181](../../frontend/src/composables/useTrace.ts)):trace-only;失败置 `degraded`/`degradedReason` 并保留已有结果,不清空。

> SSE transport `streamAgentAnalysisJob`([agent-api.ts:44-68](../../frontend/src/api/agent-api.ts))目前**无 `after=` 断线续传**(与聊天 run 的 `streamAgentRunEvents` 不同)。断流会丢中间事件,靠结尾对账兜底 —— 见 [§7](#7-改进方向)。

### 5.2 共享索引 —— `useTraceIndex.ts`

**唯一真源是 link id。** [useTraceIndex.ts](../../frontend/src/composables/useTraceIndex.ts) 是矩阵/论文/代码三处共读的派生索引。

- `selectedLinkId`(选中/pin)与 `hoveredLinkId`(仅预览,**永不改选中、永不触发跳转**)([:79-80](../../frontend/src/composables/useTraceIndex.ts))。
- `paperTargets`/`codeTargets`:`Map<targetId, view>`,每个 view 的 `links` 按 `relevance` 降序([:129-131](../../frontend/src/composables/useTraceIndex.ts))。
- `linkIdForTarget(side, targetId)` 取 `links[0]`(最高相关度)([:172-176](../../frontend/src/composables/useTraceIndex.ts)) —— **这是「一对多只显示最高相关度」的落点**。
- `summaryOf` 产 `TraceLinkSummary`(两侧摘要 + `otherLinkCount = 同 target 关系数 - 1`)([:196-224](../../frontend/src/composables/useTraceIndex.ts))。
- 仅 `proposed`/`accepted` 参与(`visibleLinks` [:86-88](../../frontend/src/composables/useTraceIndex.ts))。
- 唯一消费点:`traceIndex = useTraceIndex(trace.traceLinks)`([ProjectWorkspaceView.vue:740](../../frontend/src/views/ProjectWorkspaceView.vue))。

### 5.3 论文侧 —— `PaperReader.vue` + `trace-decorations.ts`

**滚动三通道解耦**(迭代 6 彻底重构,根治「滚轮乱跳」):
- **观测(observe)**:`IntersectionObserver` 观察所有 `h1..h6[id]`,只上报 `observeSection` 更新 TOC 高亮,**绝不 scroll**([PaperReader.vue:244-281](../../frontend/src/features/papers/PaperReader.vue))。
- **跳转意图(active)**:`activeSectionId` 仅由用户点 TOC 触发 → `scrollToSection`(smooth)([:161-171](../../frontend/src/features/papers/PaperReader.vue))。
- **关系跳转(block jump)**:`scrollToBlock`([:173-207](../../frontend/src/features/papers/PaperReader.vue))用 `holdSuppressionUntilSettled`([:98-126](../../frontend/src/features/papers/PaperReader.vue))设 `blockJumpActive`,rAF 监听 `scrollTop` 稳定 4 帧才解锁(硬上限 2.5s),期间压制 TOC 再滚动。

`usePaper.ts` 里 `observedSectionId`(观测)与 `activeSectionId`(点击意图)是两条状态([usePaper.ts:30-34](../../frontend/src/composables/usePaper.ts));`PaperOutlineTree` 高亮读 `observedSectionId` 回退 `activeSectionId`。

**装饰与锚点降级** `decoratePaperTargets`([trace-decorations.ts:167-196](../../frontend/src/features/papers/trace-decorations.ts)):
1. `blockElement`(锚点)→ 找不到则 `findBlockByQuote`(quote 全文兜底,≥12 字)([:150-160](../../frontend/src/features/papers/trace-decorations.ts))。
2. 两者都失败 → 记入 `unresolved` 集([:176-179](../../frontend/src/features/papers/trace-decorations.ts))。
3. 命中后 `wrapOccurrence` 精确包 `<mark>`,失败则退块级 `trace-block-target`。
4. 数学块:`resolveVisualBlock`([:40-53](../../frontend/src/features/papers/trace-decorations.ts))从空 `<p>` 包裹的 span 跳到下一个 `.math-display`。

`unresolvedTargetIds` 暴露给视图,渲染「论文锚点不可用(后端未解析该块)」。公式静态色:`.math-display.trace-block-target` 有独立浅蓝底 + outline([PaperReader.vue:559-573](../../frontend/src/features/papers/PaperReader.vue)),未选中也可见。

### 5.4 代码侧 —— `CodeEditor.vue`

CodeMirror 6 `StateField` + `Decoration.mark`([CodeEditor.vue:82-148](../../frontend/src/features/repository/CodeEditor.vue))。`targetRange` 优先 `char_start/end`,否则 `matchLine*`/`line*` 映射到文档行。`domEventHandlers`([:169-190](../../frontend/src/features/repository/CodeEditor.vue)):`mouseover`→hover(对 CM 逐 token 拆分做去重)、`mousedown`→select。`goToLine`([:394-404](../../frontend/src/features/repository/CodeEditor.vue))选中整行并居中。

> 注意:代码侧的一次性 reveal **不**走 `CodeEditor` 的 `revealActive`(视图传 `:reveal-active="false"`),而由父级 `selectedLinkId` watch 里的 `jumpToCode` 驱动(见 §5.5)。`revealActiveCodeTarget` 在本视图里事实上休眠。

### 5.5 装配 —— `ProjectWorkspaceView.vue`

- **选中 → 一次性双侧跳转**:`selectedLinkId` watch([:1099-1117](../../frontend/src/views/ProjectWorkspaceView.vue))变化时,论文 `scrollToBlock(block, quote)` + 代码 `jumpToCode(path, match_line_start ?? line_start, match_line_end ?? line_end)`。**只 watch `selectedLinkId`**(非 hover),所以悬浮不会触发跳转。
  - 切文件会**异步重建** CodeMirror 视图(语言模式是动态 import),所以 `goToLine` 在视图尚未挂载时把请求**排队**,由 `mountEditor` 按路径校验后重放([CodeEditor.vue](../../frontend/src/features/repository/CodeEditor.vue))。否则跳转会静默丢失,代码栏停在文件顶部 —— 那里往往正好有**另一条**追溯目标的蓝色装饰,看起来就像「跳到了错误的行」。
  - reveal 用 `scrollIntoView(pos, { y: 'center' })` 居中,并在下一帧重发一次(新建视图尚未完成测量时首次滚动会偏短);命中区间较短时居中整段,较长时居中首行。
- **固定摘要框 + 悬浮预览框**(右下角 `position:fixed`):固定框显示选中关系两侧摘要 + 分数 + rationale;悬浮不同关系时上方叠临时预览框;`hoveredSummary` 在 hover===selected 时返回 null,避免重复。
  - 「论文锚点不可用」:`selectedPaperUnresolved` 查 `paperReaderRef.unresolvedTargetIds`([:754-758](../../frontend/src/views/ProjectWorkspaceView.vue))。
  - 「另有 N 条更低相关度关系」:读 `otherLinkCount`([:625-627](../../frontend/src/views/ProjectWorkspaceView.vue))。
- **摘要列宽可调**:`--trace-summary-width` CSS 变量 + 拖拽分隔条,`localStorage 'tracelab.traceSummary.width'` 持久化,夹取 [180,480]([:798-805](../../frontend/src/views/ProjectWorkspaceView.vue))。
- **Esc 取消固定** → `traceIndex.unselect()`([:845-847](../../frontend/src/views/ProjectWorkspaceView.vue))。
- **Agent 进度条**:不确定进度(无 N/100 分母),显示离散步数 + 活动文案 + 滚动日志。

### 5.6 矩阵 —— `TraceMatrix.vue`

整行 `@click`=select、`@mouseenter`=hover、`@mouseleave`=leave([TraceMatrix.vue:46-48](../../frontend/src/features/tracing/TraceMatrix.vue));选中行高亮 `row.id === selectedId`;接受/拒绝按钮仅对 `proposed` 行、`@click.stop` 发 `review`。

---

## 6. 不变量(改动前必读)

后续 agent 修改本系统时,**下列约束不能破坏**,否则会退回历史迭代已修过的 bug:

1. **证据不许伪造**:任何「让追溯更多/更省」的改动,不得绕过 `_validate_traces` 的 occurrence+quote_hash 校验。宁可丢候选,不可放行未命中的 quote。
2. **人工决策不可覆盖**:`_persist_trace_links` 必须继续跳过 `accepted`/`rejected` link([analysis_jobs.py:416-418](../../backend/app/services/agent/analysis_jobs.py))。
3. **选中是唯一真源**:前端跳转只能挂在 `selectedLinkId` 上,**永远不要**让 hover 或滚动观测触发 `scrollTo`/`jumpToCode`。这是「悬浮乱跳/滚轮乱跳」的历史根因(迭代 5、6)。
4. **观测 ≠ 意图**:论文侧 `IntersectionObserver` 只能 `emit('observeSection')`,不得回写会触发滚动的 `activeSectionId`。
5. **`$$` 锚点安全线**:改 `paper_markdown.py` 时,span 绝不能落进数学定界符内(会破坏 KaTeX)。
6. **渐进发布幂等**:trace publish 是非终止的、可多次的;links 靠 `trace_fingerprint` 幂等累加,别改成「每批建新 artifact」(迭代 3 修过互相清除)。
7. **协调器不抛异常、不自动跑 architecture**:`maybe_start_trace` 失败必须静默;追溯交付不得依赖架构图/张量图。
8. **provider 不可用时降级而非伪造**:不得用本地静态规则冒充语义追溯结果。

---

## 7. 改进方向

按「价值 / 改动面」大致排序。每项标了下手文件,供后续 agent 直接接。

### 7.1 后端锚点覆盖率(最高优先,数据层短板)
**现象**:部分块 `anchor_resolved=False`(如 p3-b53),论文侧只能靠前端 quote 兜底、常兜不住,显示「锚点不可用」。
**根因**:`inject_block_anchors` 的**前缀匹配**对含大量内联公式/被 MinerU 切碎的块召回率不足([paper_markdown.py:150-166](../../backend/app/services/paper_markdown.py))。
**方向**:
- 前缀匹配失败时加**多锚点/子串锚点**回退(用块内最长纯文本 run 定位),或注入**块级注释锚点**而非依赖文本前缀。
- 或改为 MinerU 解析时就记录每块的字符区间,渲染期直接按区间注入,不做文本再匹配。
- 落地后回填 `anchor_status` 统计,给出「本论文锚点覆盖 X/Y」的可观测指标。

### 7.2 软目标启发式过粗
`soft = 18 + 2*n_formula + blocks//30`([analysis_jobs.py:582-601](../../backend/app/services/agent/analysis_jobs.py))只数公式块,没考虑代码规模、方法章节密度。
**方向**:纳入 `symbols_json` 规模、方法章节 must-inspect 对象数;或改为「连续 K 次发布无新增即收敛」的动态判据,而非纯步数。

### 7.3 反向覆盖度自检
当前没有「每个 must-inspect 论文目标是否 linked 或 unresolved」的**终态强校验**,靠 prompt 自觉。
**方向**:在 `_finalize_trace_run`([:604-640](../../backend/app/services/agent/analysis_jobs.py))加一步:列出未覆盖的 must-inspect 目标,写入 artifact 供前端展示「覆盖 X/Y 核心目标」。这也是评测质量门的前置。

### 7.4 SSE 断线续传
`streamAgentAnalysisJob` 无 `after=` 游标([agent-api.ts:44-68](../../frontend/src/api/agent-api.ts)),长追溯断网会丢中间 `analysis.published`(结尾对账能补齐最终态,但过程渲染会跳)。
**方向**:参照聊天 `streamAgentRunEvents` 的断线续传,加 `after=sequence`。

### 7.5 一对多的可切换 UI
现在只显示 `links[0]` + 「另有 N 条」计数,无法查看/切换其余关系。
**方向**:固定框内列出该 target 的多条候选(已按 relevance 排序),点候选=选中那条 link(走统一 `select`,复用现有跳转)。改动集中在 `ProjectWorkspaceView.vue` 固定框模板 + 无需动索引(`paperTargets` 已存全部 links)。

### 7.6 评测与质量门(§12 蓝图,尚未落地)
无固定样例集、无可靠性指标。
**方向**:建 fixture(论文+代码+人工 GT 关系),跑 precision/recall,作为改 prompt/阈值时的回归门。

### 7.7 静态候选端点清理
`POST /trace-links/suggest` 仍在([traces.py:116-156](../../backend/app/api/routes/traces.py)),但自动链路已不用它。属历史遗留表面。
**方向**:确认无消费者后下线,或明确标注 `deprecated`。

### 7.8 architecture artifact 作为 trace 上下文
trace agent 可 `get_analysis_artifact` 读架构图,但自动流程不跑 architecture,该上下文常缺席。
**方向**:评估「按需、非阻塞地」先跑一次轻量 architecture 供 trace 参考是否提质;需先解决架构 agent 在小模型上的稳定性。

### 7.9 张量图与追溯的关系(澄清项,非 bug)
TF 项目张量图生成失败**不影响追溯**(§2、§4.3)。但两者共享上游 `symbols_json`:若整仓静态分析崩了导致 `symbols_json` 为空,`list_code_symbols` 返回空,agent 只能靠 `read_source_lines`/`search_repository_text` 摸原文,追溯质量下降(不报错)。
**方向**:前端可在 `symbols_json` 为空时给出「代码符号索引不可用,追溯精度可能下降」的提示,区分于「只是流程图没画出来」。

---

## 8. 常见任务的下手点

| 我要改… | 动这些文件 |
|---|---|
| 追溯 prompt / 四阶段策略 | `analysis_jobs.py:_system_prompt`([:174-226](../../backend/app/services/agent/analysis_jobs.py)) + `builtin_skills/trace-analysis/SKILL.md` |
| 新增/改追溯工具 | `analysis_tools.py`(`TOOL_MODELS`/`TOOL_DESCRIPTIONS`/`tool_definitions` 白名单 + `execute_tool` 分支) |
| 发布证据 schema / 分数 | `analysis_tools.py`(`TraceCandidate`/`TracePaperEvidence`/`TraceCodeEvidence`)+ 前端 `types/tracing.ts` |
| 证据校验 / 锚定逻辑 | `analysis_tools.py:_validate_traces` + `anchoring.py` |
| 落库字段 / target 去重 | `analysis_jobs.py:_persist_trace_links`/`_upsert_*_target` + `entities.py` + 新迁移 |
| 终止 / 预算 / 软目标 | `analysis_jobs.py`(`_trace_soft_target`、budget、nudge、`_finalize_trace_run`) |
| 自动触发条件 | `tracing/coordinator.py:maybe_start_trace` + 四个钩子(papers/repositories/analysis_jobs/integration_settings) |
| 论文锚点注入 | `paper_markdown.py:inject_block_anchors` |
| 论文侧高亮/滚动 | `PaperReader.vue` + `trace-decorations.ts` |
| 代码侧高亮/跳转 | `CodeEditor.vue` |
| 选中/悬浮/摘要框/双侧跳转 | `useTraceIndex.ts` + `ProjectWorkspaceView.vue` |
| 矩阵行为/审阅 | `TraceMatrix.vue` |
| SSE 事件/渐进渲染 | 后端 `run_events.py`+`agent.py`;前端 `useTrace.ts`+`agent-api.ts` |

---

## 9. 术语表

- **soft target / hard cap**:软目标是「建议在 ~N 步内收敛」的提醒;硬上限是循环安全边界(trace=100)。正常终止靠 `finish_analysis`,不是靠步数跑满。
- **occurrence**:quote 在其 block(论文)或行区间(代码)内的**第几次出现**。同一 quote 重复时必须给对,否则锚不到。
- **relevance / confidence / salience**:边的「代码实现程度」/ 边的「确定性」/ 目标的「重要程度」。三者独立,不可混用。
- **anchor_resolved**:后端前缀匹配是否成功注入了该块的 DOM 锚点。False 时前端走 quote 兜底或「锚点不可用」。
- **渐进发布(progressive publish)**:trace publish 非终止、可多次,每批立即校验落库并发 `analysis.published`,前端边分析边渲染。
- **观测 vs 意图**:论文侧 TOC 高亮跟随滚动(观测,IntersectionObserver,不滚)与用户点 TOC 跳转(意图,唯一允许 scrollTo)两条通道,严格分离。
- **单 artifact 复用**:一次 run 只建一个 `AgentAnalysisArtifact`,后续批次追加 links,按内容指纹幂等。
