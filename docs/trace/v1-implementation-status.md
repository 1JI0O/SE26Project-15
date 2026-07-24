# 追溯 V1 实现状态

## 2026-07-24 前端 UI 修复（`fix/frontend-trace-ux`）

### 问题与根因

| 问题 | 根因 | 修复 |
|------|------|------|
| 悬浮面板/审阅按钮边界抖动 | 右下角 `trace-box` 遮挡论文 mark，触发 mouseout/mouseover 循环 | `pointer-events: none` + 交互子元素恢复 auto |
| 滚动时高亮消失 | 临时 `paper-block-highlight` 固定 1.8s 计时，滚动未结束即淡出 | 滚动稳定后再启动 3.2s 淡出计时 |
| 公式无常驻高亮 | `wrapOccurrence` 在段落内匹配 plainLead（如 `L_{3D}`），跳过 block-fallback | 公式/数学类 target 强制 block-fallback + 就近查找 `.math-display` |
| 一对多/多对一无视觉区分 | 仅 `linkIdForTarget` 取最高相关度，mark 无角标/配色 | `multiplicity` + `fanoutCount` + 紫/青配色 + `×N` 角标 |
| 代码→论文跳转偏移 | `scrollToBlock` 按段落顶对齐（-20% 视口） | 优先 `mark[data-trace-target]` 居中滚动 |
| 重新生成不清空 | `generateSuggestions` 仅在完成后 `loadTraceRows` | `force=true` 时立即清空 links/rows 与选中态 |

### 色彩语义（论文 + 代码两侧一致）

- **蓝色下划线/底**：`proposed` 候选关系（1 对 1）
- **绿色下划线/底**：`accepted` 已接受关系（1 对 1）
- **紫色下划线 + `×N` 角标**：`1_to_n` 一对多（一个片段对应 N 个代码/论文目标）
- **青色下划线 + `×N` 角标**：`n_to_1` 多对一（多个片段共享同一目标）
- **紫+青双层下划线**：`n_to_n` 多对多
- **黄色强描边**：当前选中的追溯关系（`selectedLinkId`）
- **浅黄描边**：悬停预览（`hoveredLinkId`，不改变选中）
- **亮黄块 `paper-block-highlight`**：跳转后的临时闪烁（3.2s，非常驻）

### 多对多跳转策略（当前迭代）

- 点击 mark / 矩阵行 / 代码高亮：仍取该 target 下 **相关度最高** 的一条 link（`links[0]`）。
- 固定面板显示「另有 N 条更低相关度关系」；完整切换 UI 留待后续迭代。

### 涉及文件

- `frontend/src/composables/useTraceIndex.ts` — multiplicity / fanoutCount 索引
- `frontend/src/features/papers/trace-decorations.ts` — 论文 mark 装饰与公式 block-fallback
- `frontend/src/features/papers/PaperReader.vue` — 跳转、去抖、样式
- `frontend/src/features/repository/CodeEditor.vue` — 代码侧 multiplicity 装饰
- `frontend/src/features/tracing/TraceMatrix.vue` — 图例 + 审阅后 clear hover
- `frontend/src/views/ProjectWorkspaceView.vue` — 面板 pointer-events、调用链
- `frontend/src/composables/useTrace.ts` — 重新生成即时清空
