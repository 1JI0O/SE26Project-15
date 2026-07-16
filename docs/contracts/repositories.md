# 代码仓库与张量流接口契约

本文描述技术原型迭代中的代码仓库导入、静态分析、安全文件访问和张量流接口。统一前缀为 `/api/v1/projects/{project_id}`。

## 1. 导入代码仓库

### 上传 ZIP

`POST /code`

使用 `multipart/form-data`，文件字段名为 `file`，仅接受 `.zip` 文件。ZIP 中的绝对路径、路径穿越成员、符号链接、超量文件和超大解压体积不会进入分析链路；无效 ZIP 返回 `400`。

### 导入 GitHub 仓库

`POST /code/github`

请求：

```json
{
  "url": "https://github.com/pytorch/vision"
}
```

只接受无凭据、无查询参数的 HTTPS `github.com/{owner}/{repository}` URL。服务端执行受参数约束的浅克隆，并将 Git 跟踪文件打包后复用 ZIP 分析链路。超时由 `GITHUB_CLONE_TIMEOUT_SECONDS` 配置，默认 60 秒。

两个导入接口均返回仓库记录、文件索引、符号、导入、调用、张量语义图和摘要。摘要字段包括过滤后文件数、Python 文件数、符号数、调用数、忽略文件数和总字节数。

## 2. 过滤规则

分析器按以下顺序建立允许文件集合：

1. 拒绝不安全 ZIP 成员和 ZIP 符号链接。
2. 应用内置系统/构建产物规则。
3. 应用仓库根目录和子目录中的 `.gitignore`。
4. 应用 `.git/info/exclude`。
5. 剥离 ZIP 唯一公共顶层目录，所有 API 路径均使用剥离后的相对路径。

内置规则覆盖 `.DS_Store`、`._*`、`__MACOSX`、`.git`、`.venv`、`node_modules`、`dist`、`build`、缓存目录和 Python 字节码等常见产物。被过滤文件不会出现在文件树、分析、读取或保存接口中。

## 3. 静态分析

`GET /code/analysis`

响应核心结构：

```json
{
  "symbols": [
    {
      "id": "models/resnet.py::BasicBlock.forward",
      "kind": "method",
      "type": "method",
      "name": "forward",
      "path": "models/resnet.py",
      "line": 24,
      "line_start": 24,
      "line_end": 31,
      "qualified_name": "BasicBlock.forward",
      "args": ["self", "x"]
    }
  ],
  "imports": [],
  "calls": [
    {
      "id": "models/resnet.py:25:14:self.conv1",
      "caller_symbol_id": "models/resnet.py::BasicBlock.forward",
      "callee": "self.conv1",
      "path": "models/resnet.py",
      "line_start": 25,
      "line_end": 25,
      "column_start": 14,
      "column_end": 27
    }
  ],
  "pytorch_candidates": [],
  "tensor_graph": {
    "nodes": [],
    "edges": [],
    "entry_symbols": ["models/resnet.py::BasicBlock.forward"],
    "shape_status": "unknown",
    "shape_reason": "Runtime shape propagation was not requested or is unavailable"
  },
  "summary": {
    "file_count": 12,
    "python_file_count": 8,
    "symbol_count": 24,
    "call_count": 37,
    "ignored_count": 9,
    "total_bytes": 48192
  }
}
```

符号 ID 固定为 `{规范化相对路径}::{限定名}`。源码行号从 1 开始；`line_end` 为包含式结束行。调用位置同时提供从 0 开始的 AST 列偏移。

## 4. 分层模型架构图与张量语义图

分析器保留两种用途不同的图。默认架构图先从 PyTorch 模块组合关系中识别主模型，沿真实 `forward` 或其委托的 `forward_step` 提取输入、模块调用、关键融合和输出；损失、数据集、渲染器等辅助类不进入默认总览。原有语句级分析继续识别函数调用、张量二元运算、条件分支、残差、`torch.cat/concat/stack` 和返回值，作为按模块查看的调试图。

语义节点不包含布局坐标：

```json
{
  "id": "models/resnet.py::BasicBlock.forward#30:8:7",
  "op": "add",
  "label": "out add",
  "kind": "merge",
  "description": "In-place tensor add merges two data-flow branches.",
  "symbol_id": "models/resnet.py::BasicBlock.forward",
  "shape": null,
  "shape_reason": "Static analysis cannot determine runtime tensor dimensions",
  "source_path": "models/resnet.py",
  "line_start": 30,
  "line_end": 30,
  "metadata": {}
}
```

边的 `kind` 可为 `tensor`、`control`、`branch` 或 `residual`。当前迭代不伪造静态 shape；未执行运行时 shape propagation 时必须返回 `null` 和原因。

`GET /workspace/tensor-flow` 默认返回 `view=architecture`，`renderer` 为 `architecture-dag-v2`。可使用以下查询参数：

- `view=architecture|debug`：切换模块级架构图或当前模块的语句级调试图。
- `root_symbol={path}::{ClassName}`：选择主模型或下钻到 `expandable=true` 的自定义组件。

响应通过 `root_symbol`、`root_label` 和 `available_roots` 描述当前层级；节点通过 `component_symbol_id`、`expandable`、`external` 区分可下钻的自定义模块与默认折叠的外部黑盒。两种视图均增加 `x`、`y`、`width`、`height` 和正交边 `points`。前端应使用 `source_path`、`line_start`、`line_end` 跳转源码，不应依赖节点 ID 推断路径。

图分析结果按仓库修订持久化。响应包含 `analysis_status`、`analysis_revision`、`repository_revision` 和 `stale`：

- 小仓库可在上传请求内完成分析；超过 `TRACELAB_ANALYSIS_INLINE_MAX_BYTES` 时先返回文件树并进入后台队列。
- 保存代码后仓库修订递增，旧图可作为 `stale=true` 缓存继续显示，后台任务完成后原子替换为新修订结果。
- `GET /workspace/tensor-flow` 不重新解压或分析仓库，只读取缓存并在缺失/过期时尽力触发任务。
- 服务启动会恢复 `queued/running` 任务，并为旧数据库中缺少新缓存的仓库补算。

## 5. 文件树、读取与保存

`GET /workspace/code-tree` 返回完整过滤后树。目录节点包含 `child_count`、`descendant_count` 和 `has_children`，可用于后续懒加载或分页；文件节点包含 `size`。

`GET /workspace/code-files/{file_path}` 读取 UTF-8 文本。

`PUT /workspace/code-files/{file_path}` 请求：

```json
{
  "content": "class Model:\n    pass\n"
}
```

读写路径必须是允许集合中的规范化仓库相对路径。保存写入项目内按仓库记录隔离的编辑覆盖层，不修改原 ZIP，也不会在替换代码仓库后复用旧编辑。服务端在读取覆盖内容前仍会验证原文件属于允许集合。
成功保存会递增仓库 `revision`，并将引用旧修订号的 proposed/accepted 追溯关系标记为 `stale`；手工编辑与 Agent 确认后的编辑复用同一保存链路。

| 状态码 | 场景 |
|---:|---|
| `400` | 绝对路径、`..` 路径穿越或非法规范化路径 |
| `404` | 仓库未导入、文件不存在或文件已被忽略 |
| `413` | 原文件或待保存 UTF-8 内容超过 512000 字节 |
| `415` | 扩展名受限、包含 NUL 字节或不是合法 UTF-8 文本 |

编辑覆盖目录中的符号链接逃逸同样被拒绝。

## 6. 已知限制

- 静态分析不执行用户仓库代码，无法保证动态调用、反射和运行时 shape 的完整性。
- 跨文件解析当前按唯一类名提供候选 `resolved_symbol_id`，不等价于完整 Python import resolution。
- `nn.Sequential` 当前作为单个语义节点返回构造组件元数据，不展开为经过运行时验证的逐层 shape 图。
- GitHub 导入依赖本机 `git` 和网络可用性；失败不会创建仓库数据库记录。
