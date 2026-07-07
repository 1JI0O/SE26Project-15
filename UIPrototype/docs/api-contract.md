# 接口契约

后端统一前缀为 `/api/v1`。运行后可访问 `/docs` 查看自动生成的 OpenAPI 文档。

## 健康检查

`GET /api/v1/health`

响应：

```json
{
  "status": "ok",
  "service": "Paper Code Trace Workbench"
}
```

## 项目

`GET /api/v1/projects`

返回项目列表。

`POST /api/v1/projects`

请求：

```json
{
  "name": "ResNet 论文复现",
  "description": "追溯论文段落与 PyTorch 实现"
}
```

`GET /api/v1/projects/{project_id}`

返回项目详情。

## 论文

`POST /api/v1/projects/{project_id}/paper`

表单上传字段：`file`，仅第一迭代约定为 PDF。

返回：

```json
{
  "id": 1,
  "project_id": 1,
  "filename": "paper.pdf",
  "title": "Paper Title",
  "abstract": "Abstract text",
  "sections": [],
  "paragraphs": []
}
```

`GET /api/v1/projects/{project_id}/paper`

返回该项目最新论文解析结果。

## 代码仓库

`POST /api/v1/projects/{project_id}/code`

表单上传字段：`file`，第一迭代约定为 ZIP 包。

返回：

```json
{
  "id": 1,
  "project_id": 1,
  "filename": "repo.zip",
  "file_tree": [],
  "symbols": [],
  "imports": [],
  "pytorch_candidates": []
}
```

`GET /api/v1/projects/{project_id}/code`

返回该项目最新代码分析结果。

## 追溯关系

`GET /api/v1/projects/{project_id}/trace-links`

返回已保存的追溯关系。

`POST /api/v1/projects/{project_id}/trace-links`

请求：

```json
{
  "paper_ref": "paragraph:12",
  "code_ref": "models/resnet.py:ResNet",
  "relation_type": "implements",
  "confidence": 0.82,
  "rationale": "该代码类实现了论文中的残差网络结构。"
}
```

`POST /api/v1/projects/{project_id}/trace-links/suggest`

基于当前论文与代码分析结果生成候选追溯关系。第一迭代为启发式示例，后续可替换为 embedding/LLM/规则混合方案。

## 完整工作台 UI 占位接口

以下接口用于支撑最终形态 UI 的后续开发。当前返回稳定的占位 JSON，不代表流程图、魔改冲突分析、报告生成等算法已经实现。

`GET /api/v1/projects/{project_id}/workspace`

返回完整工作台聚合数据，包含导入步骤、论文页、代码文件、追溯矩阵、流程图、冲突项和报告摘要。`project_id` 可使用真实项目 ID，也可使用 `prototype` 查看占位数据。

`GET /api/v1/projects/{project_id}/workspace/paper-pages`

返回论文原文页占位数据：

```json
[
  {
    "page_number": 3,
    "title": "3.1 Residual Building Block",
    "body": ["Formally, a building block is defined as y = F(x, Wi) + x."],
    "anchors": [{"id": "P3-12", "kind": "formula", "text": "y = F(x, Wi) + x"}]
  }
]
```

`GET /api/v1/projects/{project_id}/workspace/code-tree`

返回代码文件树/文件摘要占位数据。

`GET /api/v1/projects/{project_id}/workspace/code-files/{file_path}`

返回指定代码文件内容、关联行和论文引用信息。`file_path` 支持斜杠路径，例如 `models/resnet.py`。

`GET /api/v1/projects/{project_id}/workspace/trace-matrix`

返回论文位置与代码位置的双向追溯矩阵占位数据。

`GET /api/v1/projects/{project_id}/workspace/flow-graph`

返回流程图节点占位数据。

`GET /api/v1/projects/{project_id}/workspace/conflicts`

返回魔改冲突分析占位数据。

`GET /api/v1/projects/{project_id}/workspace/report-summary`

返回报告摘要和质量门禁卡片占位数据。

`POST /api/v1/projects/{project_id}/workspace/analyze`

启动完整工作台分析任务的占位接口，当前只返回 `202 Accepted` 与 placeholder job id。

请求：

```json
{
  "mode": "full",
  "targets": ["models/resnet.py"]
}
```
