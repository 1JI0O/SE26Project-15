from typing import Any


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
                "title": "生成追溯视图",
                "description": "组合规则、向量检索和大模型解释，输出候选关系与审阅理由。",
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
                "title": "PDF 结构化",
                "description": "页码、段落、公式、图表、算法框与引用统一生成锚点。",
            },
            {
                "stage": "B",
                "title": "代码静态分析",
                "description": "文件树、符号、调用链、配置项和实验脚本进入索引。",
            },
            {
                "stage": "C",
                "title": "候选追溯生成",
                "description": "规则匹配、embedding 检索和 LLM 解释共同生成候选。",
            },
            {
                "stage": "D",
                "title": "人工确认与报告",
                "description": "确认、驳回、补充证据，最终输出可复审报告。",
            },
        ],
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
