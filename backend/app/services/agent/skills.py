from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentSkill:
    name: str
    triggers: tuple[str, ...]
    preferred_tools: tuple[str, ...]
    instructions: str


SKILLS = (
    AgentSkill(
        name="paper_explanation",
        triggers=("论文", "公式", "算法", "方法", "paper", "equation", "explain"),
        preferred_tools=("search_paper", "get_paper_block", "list_trace_links"),
        instructions=(
            "先检索论文原文并引用明确段落；区分论文事实、代码事实与推断。"
            "涉及公式到代码的对应关系时必须再读取代码或追溯证据。"
        ),
    ),
    AgentSkill(
        name="architecture_analysis",
        triggers=("流程图", "架构", "张量", "transformer", "cnn", "graph", "architecture"),
        preferred_tools=("get_architecture", "get_graph_node", "focus_architecture"),
        instructions=(
            "优先使用模块级架构视图；只有排查细节时才切换 debug。"
            "经典或外部组件默认作为黑盒，不把低层算子混入总览。"
        ),
    ),
    AgentSkill(
        name="trace_analysis",
        triggers=("追溯", "对应", "实现", "关系", "trace", "mapping"),
        preferred_tools=("search_paper", "search_code", "list_trace_links", "get_trace_detail"),
        instructions=(
            "每个追溯结论必须同时具备论文和代码证据；置信度不足时明确不确定性。"
            "修改追溯状态或创建关系必须走确认工具。"
        ),
    ),
    AgentSkill(
        name="code_change",
        triggers=("修改", "修复", "重构", "实现", "代码", "edit", "fix", "refactor"),
        preferred_tools=(
            "search_code",
            "read_code_file",
            "propose_code_patch",
            "analyze_change_risk",
            "save_code_file",
        ),
        instructions=(
            "修改前读取完整相关文件和调用上下文；先生成 diff，再进行风险分析。"
            "保存必须使用最新 base_sha256，且所有写操作等待用户确认。"
        ),
    ),
    AgentSkill(
        name="risk_analysis",
        triggers=("风险", "冲突", "影响", "回归", "risk", "conflict", "regression"),
        preferred_tools=("analyze_change_risk", "list_trace_links", "search_code"),
        instructions=(
            "检查受影响符号、调用者、已接受追溯和仓库修订；按证据给出风险级别，"
            "不得仅凭文件名宣称安全。"
        ),
    ),
)


def select_skills(message: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    lowered = message.lower()
    selected = [
        skill for skill in SKILLS if any(trigger.lower() in lowered for trigger in skill.triggers)
    ]
    if context.get("graph") and not any(
        skill.name == "architecture_analysis" for skill in selected
    ):
        selected.append(next(skill for skill in SKILLS if skill.name == "architecture_analysis"))
    if not selected:
        selected = [SKILLS[0]]
    return [
        {
            "name": skill.name,
            "preferred_tools": list(skill.preferred_tools),
            "instructions": skill.instructions,
        }
        for skill in selected[:3]
    ]


def system_prompt(skills: list[dict[str, Any]]) -> str:
    skill_text = "\n".join(f"- {skill['name']}: {skill['instructions']}" for skill in skills)
    return (
        "You are TraceLab Agent, an evidence-driven coding and paper-research agent "
        "embedded in an IDE.\n"
        "Operate through the provided tools. Never claim a file, paper statement, graph "
        "edge, or trace relation that was not observed in context or tool output. Read "
        "before editing. Treat tool errors as recoverable: inspect the error, correct "
        "arguments, and retry with a different valid step. Never retry the same invalid "
        "call unchanged. Code writes, trace mutations, and analysis reruns require "
        "explicit confirmation. For code changes, propose a patch and run risk analysis "
        "before save_code_file. Cite evidence in the final answer using refs returned by "
        "tools. Keep answers concise but state uncertainty and remaining risks.\n"
        "Active skills:\n"
        f"{skill_text}"
    )
