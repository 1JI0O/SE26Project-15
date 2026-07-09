from typing import Any


def _code_tree() -> list[dict[str, Any]]:
    return [
        {
            "name": "resnet-reproduction",
            "path": "",
            "kind": "folder",
            "meta": "root",
            "children": [
                {
                    "name": "configs",
                    "path": "configs",
                    "kind": "folder",
                    "meta": "1 file",
                    "children": [
                        {
                            "name": "resnet50.yaml",
                            "path": "configs/resnet50.yaml",
                            "kind": "file",
                            "meta": "config",
                            "children": [],
                        }
                    ],
                },
                {
                    "name": "data",
                    "path": "data",
                    "kind": "folder",
                    "meta": "2 files",
                    "children": [
                        {
                            "name": "imagenet.py",
                            "path": "data/imagenet.py",
                            "kind": "file",
                            "meta": "loader",
                            "children": [],
                        },
                        {
                            "name": "transforms.py",
                            "path": "data/transforms.py",
                            "kind": "file",
                            "meta": "pipeline",
                            "children": [],
                        },
                    ],
                },
                {
                    "name": "models",
                    "path": "models",
                    "kind": "folder",
                    "meta": "3 files",
                    "children": [
                        {
                            "name": "__init__.py",
                            "path": "models/__init__.py",
                            "kind": "file",
                            "meta": "module",
                            "children": [],
                        },
                        {
                            "name": "layers.py",
                            "path": "models/layers.py",
                            "kind": "file",
                            "meta": "ops",
                            "children": [],
                        },
                        {
                            "name": "resnet.py",
                            "path": "models/resnet.py",
                            "kind": "file",
                            "meta": "8 links",
                            "children": [],
                        },
                    ],
                },
                {
                    "name": "train.py",
                    "path": "train.py",
                    "kind": "file",
                    "meta": "entry",
                    "children": [],
                },
                {
                    "name": "evaluate.py",
                    "path": "evaluate.py",
                    "kind": "file",
                    "meta": "script",
                    "children": [],
                },
                {
                    "name": "README.md",
                    "path": "README.md",
                    "kind": "file",
                    "meta": "doc",
                    "children": [],
                },
            ],
        }
    ]


def _code_files() -> list[dict[str, Any]]:
    return [
        {
            "path": "models/resnet.py",
            "name": "models/resnet.py",
            "badge": "8 links",
            "status": "与论文强关联",
            "status_type": "success",
            "symbol": "BasicBlock.forward",
            "paper_ref": "P3-12, P3-17",
            "linked_lines": [12, 13, 17, 18, 19, 21],
            "content": "\n".join(
                [
                    "import torch",
                    "import torch.nn as nn",
                    "",
                    "",
                    "class BasicBlock(nn.Module):",
                    "    expansion = 1",
                    "",
                    "    def __init__(self, inplanes, planes, stride=1, downsample=None):",
                    "        super().__init__()",
                    "        self.conv1 = conv3x3(inplanes, planes, stride)",
                    "        self.bn1 = nn.BatchNorm2d(planes)",
                    "        self.relu = nn.ReLU(inplace=True)",
                    "        self.conv2 = conv3x3(planes, planes)",
                    "        self.bn2 = nn.BatchNorm2d(planes)",
                    "        self.downsample = downsample",
                    "        self.stride = stride",
                    "",
                    "    def forward(self, x):",
                    "        identity = x",
                    "        out = self.relu(self.bn1(self.conv1(x)))",
                    "        out = self.bn2(self.conv2(out))",
                    "        if self.downsample is not None:",
                    "            identity = self.downsample(x)",
                    "        out += identity",
                    "        return self.relu(out)",
                ]
            ),
        },
        {
            "path": "models/layers.py",
            "name": "models/layers.py",
            "badge": "ops",
            "status": "张量操作候选",
            "status_type": "primary",
            "symbol": "conv3x3",
            "paper_ref": "P3-10",
            "linked_lines": [1, 2, 3],
            "content": "\n".join(
                [
                    "import torch.nn as nn",
                    "",
                    "",
                    "def conv3x3(in_planes, out_planes, stride=1):",
                    "    return nn.Conv2d(",
                    "        in_planes,",
                    "        out_planes,",
                    "        kernel_size=3,",
                    "        stride=stride,",
                    "        padding=1,",
                    "        bias=False,",
                    "    )",
                ]
            ),
        },
        {
            "path": "train.py",
            "name": "train.py",
            "badge": "3 links",
            "status": "训练流程候选",
            "status_type": "primary",
            "symbol": "train_one_epoch",
            "paper_ref": "P6-04",
            "linked_lines": [7, 8, 9],
            "content": "\n".join(
                [
                    "def train_one_epoch(model, loader, optimizer, criterion):",
                    "    model.train()",
                    "    total_loss = 0.0",
                    "",
                    "    for images, labels in loader:",
                    "        optimizer.zero_grad()",
                    "        logits = model(images)",
                    "        loss = criterion(logits, labels)",
                    "        loss.backward()",
                    "        optimizer.step()",
                    "        total_loss += loss.item()",
                    "",
                    "    return total_loss / len(loader)",
                ]
            ),
        },
        {
            "path": "configs/resnet50.yaml",
            "name": "configs/resnet50.yaml",
            "badge": "2 risks",
            "status": "配置需复核",
            "status_type": "warning",
            "symbol": "model.depth",
            "paper_ref": "P5-02",
            "linked_lines": [2, 5, 7],
            "content": "\n".join(
                [
                    "model:",
                    "  name: resnet50",
                    "  num_classes: 1000",
                    "training:",
                    "  epochs: 90",
                    "  batch_size: 256",
                    "  base_lr: 0.1",
                    "  weight_decay: 0.0001",
                ]
            ),
        },
    ]


def tensor_flow_payload(project_id: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "renderer": "trace-svg",
        "nodes": [
            {
                "id": "images",
                "label": "images",
                "kind": "input",
                "description": "训练循环中从 dataloader 取出的输入张量。",
                "source_path": "train.py",
                "line_start": 5,
                "line_end": 7,
                "tensor_shape": "N x 3 x 224 x 224",
                "x": 32,
                "y": 72,
                "width": 170,
                "height": 104,
            },
            {
                "id": "conv1",
                "label": "conv1 -> bn1 -> relu",
                "kind": "operation",
                "description": "BasicBlock.forward 中的第一段卷积、归一化和激活。",
                "source_path": "models/resnet.py",
                "line_start": 20,
                "line_end": 20,
                "tensor_shape": "N x C x H x W",
                "x": 286,
                "y": 72,
                "width": 210,
                "height": 104,
            },
            {
                "id": "conv2",
                "label": "conv2 -> bn2",
                "kind": "operation",
                "description": "残差分支中的第二段卷积和归一化。",
                "source_path": "models/resnet.py",
                "line_start": 21,
                "line_end": 21,
                "tensor_shape": "N x C x H x W",
                "x": 580,
                "y": 72,
                "width": 190,
                "height": 104,
            },
            {
                "id": "shortcut",
                "label": "identity / projection shortcut",
                "kind": "branch",
                "description": "当维度变化时进入 downsample，否则保留 identity 分支。",
                "source_path": "models/resnet.py",
                "line_start": 22,
                "line_end": 23,
                "tensor_shape": "N x C x H x W",
                "x": 286,
                "y": 306,
                "width": 300,
                "height": 108,
            },
            {
                "id": "add",
                "label": "out += identity",
                "kind": "merge",
                "description": "残差张量与 shortcut 张量相加，对应论文公式 y = F(x, Wi) + x。",
                "source_path": "models/resnet.py",
                "line_start": 24,
                "line_end": 24,
                "tensor_shape": "N x C x H x W",
                "x": 812,
                "y": 198,
                "width": 180,
                "height": 108,
            },
            {
                "id": "logits",
                "label": "model(images) -> logits",
                "kind": "output",
                "description": "模型前向输出，随后进入 loss 和 backward 训练链路。",
                "source_path": "train.py",
                "line_start": 7,
                "line_end": 8,
                "tensor_shape": "N x classes",
                "x": 812,
                "y": 360,
                "width": 180,
                "height": 104,
            },
        ],
        "edges": [
            {
                "id": "images-conv1",
                "source": "images",
                "target": "conv1",
                "label": "input tensor",
                "points": [[202, 124], [286, 124]],
            },
            {
                "id": "conv1-conv2",
                "source": "conv1",
                "target": "conv2",
                "label": "feature tensor",
                "points": [[496, 124], [580, 124]],
            },
            {
                "id": "conv2-add",
                "source": "conv2",
                "target": "add",
                "label": "residual",
                "points": [[770, 124], [792, 124], [792, 252], [812, 252]],
            },
            {
                "id": "images-shortcut",
                "source": "images",
                "target": "shortcut",
                "label": "identity branch",
                "points": [[118, 176], [118, 360], [286, 360]],
            },
            {
                "id": "shortcut-add",
                "source": "shortcut",
                "target": "add",
                "label": "shortcut tensor",
                "points": [[586, 360], [700, 360], [700, 278], [812, 278]],
            },
            {
                "id": "add-logits",
                "source": "add",
                "target": "logits",
                "label": "block output",
                "points": [[902, 306], [902, 360]],
            },
        ],
    }


def workspace_payload(project_id: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "project_name": "ResNet 论文复现",
        "import_steps": [
            {
                "index": "01",
                "title": "导入论文 PDF",
                "description": "保留原文页视图，抽取章节、段落、公式、图表和引用锚点。",
                "status": "已解析",
                "tag_type": "success",
                "action": "重新上传",
            },
            {
                "index": "02",
                "title": "导入代码 ZIP",
                "description": "按 .gitignore 过滤文件，生成目录树、符号表、调用关系和配置索引。",
                "status": "已分析",
                "tag_type": "success",
                "action": "替换代码包",
            },
            {
                "index": "03",
                "title": "生成代码追踪视图",
                "description": "基于代码静态分析生成可交互张量流图、追溯矩阵和冲突占位结果。",
                "status": "占位实现",
                "tag_type": "warning",
                "action": None,
            },
        ],
        "paper_pages": [
            {
                "page_number": 3,
                "title": "3.1 Residual Building Block",
                "body": [
                    "Formally, a building block is defined as y = F(x, Wi) + x.",
                    (
                        "The shortcut connection performs identity mapping and is added to "
                        "stacked layers."
                    ),
                    (
                        "When dimensions increase, projection shortcut should preserve "
                        "stride semantics."
                    ),
                ],
                "anchors": [
                    {"id": "P3-12", "kind": "formula", "text": "y = F(x, Wi) + x"},
                    {"id": "P3-17", "kind": "paragraph", "text": "projection shortcut"},
                ],
            }
        ],
        "code_tree": _code_tree(),
        "code_files": _code_files(),
        "trace_rows": [
            {
                "paper_ref": "P3-12 残差公式",
                "code_ref": "models/resnet.py:BasicBlock.forward",
                "relation_type": "implements",
                "confidence": 94,
                "rationale": "残差加法 out += identity 与论文公式直接对应。",
            },
            {
                "paper_ref": "P3-17 projection shortcut",
                "code_ref": "models/resnet.py:downsample(x)",
                "relation_type": "implements",
                "confidence": 88,
                "rationale": "downsample 分支对应维度变化时的 projection shortcut。",
            },
            {
                "paper_ref": "P5-02 ResNet-50 depth",
                "code_ref": "configs/resnet50.yaml:model.name",
                "relation_type": "configures",
                "confidence": 79,
                "rationale": "配置文件声明 resnet50，可进入人工确认。",
            },
        ],
        "flow_nodes": [
            {
                "stage": "A",
                "title": "输入 tensor",
                "description": "从 train.py 的 dataloader 和 model(images) 调用定位张量入口。",
            },
            {
                "stage": "B",
                "title": "模型 forward",
                "description": "追踪 BasicBlock.forward 中 conv、bn、relu 与 shortcut 分支。",
            },
            {
                "stage": "C",
                "title": "残差合并",
                "description": "识别 out += identity 对应论文残差公式 y = F(x, Wi) + x。",
            },
            {
                "stage": "D",
                "title": "输出与训练",
                "description": "连接模型输出 logits、loss 和 backward 训练链路。",
            },
        ],
        "tensor_flow": tensor_flow_payload(project_id),
        "conflict_items": [
            {
                "level": "高风险",
                "type": "danger",
                "title": "stride 下采样与论文描述不一致",
                "description": "配置中 stage3 stride 被改为 1，可能改变感受野与论文基线。",
                "affected_files": ["models/resnet.py", "configs/resnet50.yaml"],
                "status": "待人工确认",
            },
            {
                "level": "中风险",
                "type": "warning",
                "title": "训练 batch size 被缩小",
                "description": "batch size 从 256 改为 64，需要同步调整学习率或记录偏差。",
                "affected_files": ["configs/resnet50.yaml", "train.py"],
                "status": "待补充说明",
            },
        ],
        "report_cards": [
            {
                "value": "86%",
                "title": "追溯覆盖率",
                "description": "方法、模型结构和训练配置已有候选链接。",
            },
            {"value": "12", "title": "已确认关系", "description": "可进入报告的证据链数量。"},
            {"value": "3", "title": "冲突项", "description": "需要人工解释或回滚的魔改影响。"},
            {
                "value": "PDF",
                "title": "报告导出",
                "description": "支持摘要、矩阵、流程图和冲突清单。",
            },
        ],
    }


def code_file_payload(project_id: str, file_path: str) -> dict[str, Any] | None:
    for code_file in workspace_payload(project_id)["code_files"]:
        if code_file["path"] == file_path:
            return code_file
    return None
