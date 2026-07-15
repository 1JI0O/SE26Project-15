import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from app.services.code_analysis.python_ast import expression_name

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

_ROOT_PATH_PENALTIES = {
    "dataset": 90,
    "datasets": 90,
    "loss": 90,
    "losses": 90,
    "renderer": 60,
    "rendering": 60,
    "utils": 45,
    "utility": 45,
}
_ROOT_NAME_PENALTIES = (
    "datamodule",
    "dataset",
    "loss",
    "metric",
    "renderer",
    "discriminator",
)
_TRANSPARENT_CALLS = {
    "clone",
    "contiguous",
    "cpu",
    "detach",
    "float",
    "flatten",
    "item",
    "numpy",
    "permute",
    "repeat",
    "reshape",
    "squeeze",
    "to",
    "transpose",
    "unsqueeze",
    "view",
}
_LOW_LEVEL_TORCH_CALLS = {
    "arange",
    "clamp",
    "einsum",
    "exp",
    "full",
    "linspace",
    "matmul",
    "mean",
    "norm",
    "ones",
    "rand",
    "randn",
    "sigmoid",
    "softmax",
    "sum",
    "zeros",
}
_MEANINGFUL_CALL_TOKENS = (
    "attention",
    "backbone",
    "decode",
    "decoder",
    "embed",
    "encode",
    "encoder",
    "feature",
    "fusion",
    "head",
    "interpolate",
    "mano",
    "pool",
    "project",
    "projection",
    "sample",
    "transformer",
)


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [expression_name(target)]
    if isinstance(target, ast.Subscript):
        return _target_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return [name for item in target.elts for name in _target_names(item)]
    return []


def _display_name(value: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).replace("_", " ").split()
    return " ".join(
        word.upper() if word.lower() in {"cnn", "mlp", "vit", "mano"} else word.title()
        for word in words
    )


def _call_owner(node: ast.Call) -> ast.AST | None:
    return node.func.value if isinstance(node.func, ast.Attribute) else None


@dataclass
class ModuleField:
    name: str
    constructor: str
    line_start: int
    line_end: int
    component_symbol_id: str | None = None

    @property
    def label(self) -> str:
        attribute = self.name.removeprefix("self.")
        if attribute.lower() not in {"layer", "layers", "model", "module", "network"}:
            return _display_name(attribute)
        return _display_name(self.constructor.rsplit(".", 1)[-1] or attribute)


@dataclass
class ModelClass:
    symbol_id: str
    path: str
    name: str
    node: ast.ClassDef
    methods: dict[str, FunctionNode]
    modules: dict[str, ModuleField] = field(default_factory=dict)

    @property
    def line_span(self) -> int:
        return max((self.node.end_lineno or self.node.lineno) - self.node.lineno, 1)


def _collect_classes(
    sources: list[tuple[str, str, ast.Module]],
) -> dict[str, ModelClass]:
    classes: dict[str, ModelClass] = {}
    for path, _source, tree in sources:
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                child.name: child
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            if "forward" not in methods:
                continue
            symbol_id = f"{path}::{node.name}"
            classes[symbol_id] = ModelClass(symbol_id, path, node.name, node, methods)

    names: dict[str, list[str]] = {}
    for symbol_id, spec in classes.items():
        names.setdefault(spec.name, []).append(symbol_id)

    for spec in classes.values():
        init = spec.methods.get("__init__")
        if init is None:
            continue
        for node in ast.walk(init):
            if not isinstance(node, ast.Assign | ast.AnnAssign) or not isinstance(
                node.value, ast.Call
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            constructor = expression_name(node.value.func) or "dynamic module"
            component_name = constructor.rsplit(".", 1)[-1]
            matches = names.get(component_name, [])
            component_symbol_id = matches[0] if len(matches) == 1 else None
            for target in targets:
                for name in _target_names(target):
                    if not name.startswith("self."):
                        continue
                    spec.modules[name] = ModuleField(
                        name=name,
                        constructor=constructor,
                        line_start=getattr(node, "lineno", init.lineno),
                        line_end=getattr(node, "end_lineno", None)
                        or getattr(node, "lineno", init.lineno),
                        component_symbol_id=component_symbol_id,
                    )
    return classes


def _delegated_execution_method(spec: ModelClass) -> FunctionNode:
    method = spec.methods["forward"]
    visited = {"forward"}
    for _depth in range(3):
        body = [
            statement
            for statement in method.body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        ]
        if (
            len(body) != 1
            or not isinstance(body[0], ast.Return)
            or not isinstance(body[0].value, ast.Call)
        ):
            break
        callee = expression_name(body[0].value.func)
        if not callee.startswith("self."):
            break
        method_name = callee.removeprefix("self.").split(".", 1)[0]
        delegated = spec.methods.get(method_name)
        if delegated is None or method_name in visited:
            break
        visited.add(method_name)
        method = delegated
    return method


def _root_score(spec: ModelClass, referenced: set[str]) -> int:
    path = PurePosixPath(spec.path)
    lower_parts = {part.lower() for part in path.parts}
    score = 30 if spec.symbol_id not in referenced else 0
    score += 24 if "models" in lower_parts or "model" in lower_parts else 0
    score += 42 if path.stem.lower().replace("_", "") == spec.name.lower().replace("_", "") else 0
    score += min(len(spec.modules) * 4, 28)
    score += min(spec.line_span // 18, 18)
    if any(token in spec.name.lower() for token in ("model", "network", "system")):
        score += 16
    for part, penalty in _ROOT_PATH_PENALTIES.items():
        if part in lower_parts:
            score -= penalty
    if spec.name.lower().endswith(_ROOT_NAME_PENALTIES):
        score -= 100
    return score


class ArchitectureGraphBuilder:
    def __init__(
        self,
        spec: ModelClass,
        classes: dict[str, ModelClass],
        function_symbols: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.spec = spec
        self.classes = classes
        self.function = _delegated_execution_method(spec)
        self.execution_symbol = f"{spec.path}::{spec.name}.{self.function.name}"
        self.function_symbols = function_symbols
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.environment: dict[str, str] = {}
        self.counter = 0
        self.last_node: str | None = None

    def add_node(
        self,
        node: ast.AST,
        *,
        label: str,
        kind: str,
        op: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.counter += 1
        line_start = getattr(node, "lineno", self.function.lineno)
        line_end = getattr(node, "end_lineno", None) or line_start
        node_id = f"{self.execution_symbol}#architecture:{line_start}:{self.counter}"
        self.nodes.append(
            {
                "id": node_id,
                "op": op,
                "label": label,
                "kind": kind,
                "description": description,
                "symbol_id": self.execution_symbol,
                "shape": None,
                "shape_reason": "模块级静态架构视图不推断运行时张量形状",
                "source_path": self.spec.path,
                "line_start": line_start,
                "line_end": line_end,
                "metadata": {"layer": "architecture", **(metadata or {})},
            }
        )
        if kind != "input":
            self.last_node = node_id
        return node_id

    def add_edge(
        self, source: str | None, target: str, kind: str = "tensor", label: str = ""
    ) -> None:
        if not source or source == target:
            return
        if any(edge["source"] == source and edge["target"] == target for edge in self.edges):
            return
        self.edges.append(
            {
                "id": f"a{len(self.edges) + 1}:{source}->{target}",
                "source": source,
                "target": target,
                "kind": kind,
                "label": label,
            }
        )

    def _field_for_callee(self, callee: str) -> ModuleField | None:
        matches = [
            field
            for name, field in self.spec.modules.items()
            if callee == name or callee.startswith(f"{name}.")
        ]
        return max(matches, key=lambda field: len(field.name), default=None)

    def _custom_function(self, callee: str) -> dict[str, Any] | None:
        matches = self.function_symbols.get(callee.rsplit(".", 1)[-1], [])
        return matches[0] if len(matches) == 1 else None

    def _meaningful_function(self, callee: str, custom: dict[str, Any] | None) -> bool:
        suffix = callee.rsplit(".", 1)[-1].lower()
        if callee.startswith("super.") and suffix == "forward":
            return True
        if callee.startswith("self.") and suffix not in _TRANSPARENT_CALLS:
            return True
        if suffix in _TRANSPARENT_CALLS:
            return False
        if callee.startswith("torch.") and suffix in _LOW_LEVEL_TORCH_CALLS:
            return False
        if custom is not None:
            return True
        return any(token in suffix for token in _MEANINGFUL_CALL_TOKENS)

    def expression(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.environment.get(node.id)
        if isinstance(node, ast.Attribute):
            return self.environment.get(expression_name(node)) or self.expression(node.value)
        if isinstance(node, ast.Subscript):
            return self.expression(node.value)
        if isinstance(node, ast.Constant):
            return None
        if isinstance(node, ast.Call):
            previous = self.last_node
            owner = self.expression(_call_owner(node)) if _call_owner(node) is not None else None
            inputs = [owner] if owner else []
            inputs.extend(self.expression(argument) for argument in node.args)
            inputs.extend(self.expression(keyword.value) for keyword in node.keywords)
            inputs = list(dict.fromkeys(source for source in inputs if source))
            callee = expression_name(node.func) or "dynamic_call"
            field = self._field_for_callee(callee)
            custom = self._custom_function(callee)
            if field is None and not self._meaningful_function(callee, custom):
                return inputs[-1] if inputs else None

            if field is not None:
                component = self.classes.get(field.component_symbol_id or "")
                node_id = self.add_node(
                    node,
                    label=field.label,
                    kind="component",
                    op="component",
                    description=f"调用模块 {field.constructor}，对应字段 {field.name}。",
                    metadata={
                        "constructor": field.constructor,
                        "component_symbol_id": field.component_symbol_id,
                        "expandable": component is not None,
                        "external": component is None,
                    },
                )
            else:
                label = _display_name(callee.rsplit(".", 1)[-1])
                internal_method = (
                    callee.startswith("self.") and callee.rsplit(".", 1)[-1] in self.spec.methods
                )
                node_id = self.add_node(
                    node,
                    label=label,
                    kind="component",
                    op="function",
                    description=f"模型主路径中的关键函数调用：{callee}。",
                    metadata={
                        "constructor": callee,
                        "component_symbol_id": None,
                        "expandable": False,
                        "external": custom is None and not internal_method,
                    },
                )
            for source in inputs or ([previous] if previous else []):
                self.add_edge(source, node_id)
            return node_id
        if isinstance(node, ast.BinOp):
            left = self.expression(node.left)
            right = self.expression(node.right)
            if left and right and left != right:
                merge = self.add_node(
                    node,
                    label="Residual / Fusion",
                    kind="merge",
                    op="merge",
                    description="主路径中的残差连接或特征融合。",
                    metadata={"expandable": False, "external": False},
                )
                self.add_edge(left, merge, "residual")
                self.add_edge(right, merge, "residual")
                return merge
            return left or right
        if isinstance(node, ast.UnaryOp):
            return self.expression(node.operand)
        if isinstance(node, ast.Dict):
            values = [self.expression(value) for value in node.values]
            return next((value for value in reversed(values) if value), None)
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            values = [self.expression(item) for item in node.elts]
            return next((value for value in reversed(values) if value), None)
        if isinstance(node, ast.DictComp | ast.ListComp | ast.SetComp | ast.GeneratorExp):
            return self.expression(node.elt if hasattr(node, "elt") else node.key)
        return None

    def statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assign):
                value = self.expression(statement.value)
                for target in statement.targets:
                    for name in _target_names(target):
                        if value:
                            self.environment[name] = value
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                value = self.expression(statement.value)
                for name in _target_names(statement.target):
                    if value:
                        self.environment[name] = value
            elif isinstance(statement, ast.AugAssign):
                left = self.expression(statement.target)
                right = self.expression(statement.value)
                if left and right and left != right:
                    merge = self.add_node(
                        statement,
                        label="Residual / Fusion",
                        kind="merge",
                        op="merge",
                        description="主路径中的残差连接或特征融合。",
                        metadata={"expandable": False, "external": False},
                    )
                    self.add_edge(left, merge, "residual")
                    self.add_edge(right, merge, "residual")
                    for name in _target_names(statement.target):
                        self.environment[name] = merge
            elif isinstance(statement, ast.Expr):
                self.expression(statement.value)
            elif isinstance(statement, ast.If):
                before = self.environment.copy()
                self.statements(statement.body)
                body = self.environment.copy()
                self.environment = before.copy()
                self.statements(statement.orelse)
                other = self.environment.copy()
                self.environment = {
                    name: body.get(name) or other.get(name) or before.get(name)  # type: ignore[dict-item]
                    for name in before.keys() | body.keys() | other.keys()
                    if body.get(name) or other.get(name) or before.get(name)
                }
            elif isinstance(statement, ast.For | ast.AsyncFor):
                iterator = expression_name(statement.iter)
                field = self._field_for_callee(iterator)
                if field is not None:
                    previous = self.last_node
                    loop_node = self.add_node(
                        statement,
                        label=field.label,
                        kind="component",
                        op="component_collection",
                        description=f"遍历模块集合 {field.constructor}。",
                        metadata={
                            "constructor": field.constructor,
                            "component_symbol_id": field.component_symbol_id,
                            "expandable": bool(field.component_symbol_id),
                            "external": not bool(field.component_symbol_id),
                        },
                    )
                    self.add_edge(previous, loop_node)
                    for name in _target_names(statement.target):
                        self.environment[name] = loop_node
                self.statements(statement.body)
            elif isinstance(statement, ast.Return):
                source = self.expression(statement.value) if statement.value else None
                if (
                    isinstance(statement.value, ast.Name)
                    and statement.value.id.lower() in {"output", "outputs", "result", "results"}
                    and self.last_node
                ):
                    source = self.last_node
                previous = self.last_node
                output = self.add_node(
                    statement,
                    label="Output",
                    kind="output",
                    op="output",
                    description=f"{self.spec.name} 的模型输出。",
                    metadata={"expandable": False, "external": False},
                )
                self.add_edge(source or previous, output)

    def build(self) -> dict[str, Any]:
        bool_args = {
            argument.arg
            for argument in self.function.args.args
            if expression_name(argument.annotation) == "bool"
        }
        for argument in self.function.args.args:
            if (
                argument.arg == "self"
                or argument.arg in bool_args
                or argument.arg in {"train", "training"}
            ):
                continue
            input_node = self.add_node(
                argument,
                label=_display_name(argument.arg),
                kind="input",
                op="input",
                description=f"{self.spec.name} 的输入参数 {argument.arg}。",
                metadata={"expandable": False, "external": False},
            )
            self.environment[argument.arg] = input_node
        self.statements(self.function.body)
        if not any(node["kind"] == "output" for node in self.nodes):
            previous = self.last_node
            output = self.add_node(
                self.function,
                label="Output",
                kind="output",
                op="output",
                description=f"{self.spec.name} 的模型输出。",
                metadata={"expandable": False, "external": False},
            )
            self.add_edge(previous, output)
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "root_symbol": self.spec.symbol_id,
            "root_label": self.spec.name,
            "execution_symbol": self.execution_symbol,
        }


def build_architecture_index(
    sources: list[tuple[str, str, ast.Module]],
    symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    classes = _collect_classes(sources)
    function_symbols: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        if symbol.get("kind") == "function":
            function_symbols.setdefault(str(symbol.get("name", "")), []).append(symbol)

    referenced = {
        field.component_symbol_id
        for spec in classes.values()
        for field in spec.modules.values()
        if field.component_symbol_id
    }
    ranked = sorted(
        classes.values(),
        key=lambda spec: (_root_score(spec, referenced), spec.line_span),
        reverse=True,
    )
    roots = [
        {
            "symbol_id": spec.symbol_id,
            "label": spec.name,
            "source_path": spec.path,
            "score": _root_score(spec, referenced),
        }
        for spec in ranked[:12]
        if _root_score(spec, referenced) > -20
    ]
    graphs = {
        symbol_id: ArchitectureGraphBuilder(spec, classes, function_symbols).build()
        for symbol_id, spec in classes.items()
    }
    return {
        "default_root": roots[0]["symbol_id"] if roots else None,
        "roots": roots,
        "graphs": graphs,
    }
