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


def _static_callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _static_callee_name(node.value)
        return f"{owner}.{node.attr}" if owner else ""
    return ""


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


@dataclass
class ExecutionSpec:
    root_symbol: str
    execution_symbol: str
    root_label: str
    path: str
    function: FunctionNode
    owner: ModelClass | None = None


@dataclass
class ProjectCallResolution:
    target: ExecutionSpec | None = None
    unresolved_reason: str | None = None


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_bindings(path: str, tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    current_module = _module_name(path)
    package_parts = current_module.split(".")[:-1]
    if PurePosixPath(path).stem == "__init__":
        package_parts = current_module.split(".")
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bindings[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = max(len(package_parts) - node.level + 1, 0)
                prefix = package_parts[:keep]
                module_parts = node.module.split(".") if node.module else []
                module = ".".join([*prefix, *module_parts])
            else:
                module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                bindings[local] = ".".join(part for part in (module, alias.name) if part)
    return bindings


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


class ProjectCallableIndex:
    def __init__(
        self,
        executions: list[ExecutionSpec],
        imports_by_path: dict[str, dict[str, str]],
    ) -> None:
        self.imports_by_path = imports_by_path
        self.by_symbol = {execution.root_symbol: execution for execution in executions}
        self.methods: dict[tuple[str, str], ExecutionSpec] = {}
        self.functions_by_name: dict[str, list[ExecutionSpec]] = {}
        self.functions_by_canonical_name: dict[str, list[ExecutionSpec]] = {}
        self.project_modules = {_module_name(execution.path) for execution in executions}
        for execution in executions:
            if execution.owner is not None:
                method_name = execution.function.name
                self.methods[(execution.owner.symbol_id, method_name)] = execution
                continue
            self.functions_by_name.setdefault(execution.function.name, []).append(execution)
            canonical = f"{_module_name(execution.path)}.{execution.function.name}"
            self.functions_by_canonical_name.setdefault(canonical, []).append(execution)

    def canonical_callee(self, path: str, callee: str) -> str:
        root, separator, suffix = callee.partition(".")
        imported = self.imports_by_path.get(path, {}).get(root)
        if imported is None:
            return callee
        return f"{imported}.{suffix}" if separator else imported

    def resolve(self, execution: ExecutionSpec, callee: str) -> ProjectCallResolution:
        if callee == "dynamic_call":
            return ProjectCallResolution(unresolved_reason="调用目标由运行时表达式决定")
        if callee.startswith("self."):
            method_name = callee.removeprefix("self.")
            if "." not in method_name and execution.owner is not None:
                target = self.methods.get((execution.owner.symbol_id, method_name))
                if target is not None:
                    return ProjectCallResolution(target=target)
                return ProjectCallResolution(
                    unresolved_reason=f"当前类中找不到唯一方法 {callee}"
                )
            return ProjectCallResolution()

        short_name = callee.rsplit(".", 1)[-1]
        same_file = [
            candidate
            for candidate in self.functions_by_name.get(short_name, [])
            if candidate.path == execution.path
        ]
        if "." not in callee and len(same_file) == 1:
            return ProjectCallResolution(target=same_file[0])

        canonical = self.canonical_callee(execution.path, callee)
        imported = self.functions_by_canonical_name.get(canonical, [])
        if len(imported) == 1:
            return ProjectCallResolution(target=imported[0])
        if len(imported) > 1:
            return ProjectCallResolution(
                unresolved_reason=f"项目中存在多个导入目标 {canonical}"
            )

        global_matches = self.functions_by_name.get(short_name, [])
        if "." not in callee and len(global_matches) == 1:
            return ProjectCallResolution(target=global_matches[0])
        if "." not in callee and len(global_matches) > 1:
            return ProjectCallResolution(
                unresolved_reason=f"项目中存在多个名为 {short_name} 的函数"
            )
        if canonical != callee and any(
            canonical == module or canonical.startswith(f"{module}.")
            for module in self.project_modules
        ):
            return ProjectCallResolution(
                unresolved_reason=f"导入的项目调用 {callee} 无法定位到唯一函数"
            )
        return ProjectCallResolution()


class ArchitectureGraphBuilder:
    def __init__(
        self,
        execution: ExecutionSpec,
        classes: dict[str, ModelClass],
        callables: ProjectCallableIndex,
    ) -> None:
        self.execution = execution
        self.spec = execution.owner
        self.classes = classes
        self.function = execution.function
        self.execution_symbol = execution.execution_symbol
        self.callables = callables
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
                "source_path": self.execution.path,
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
        if self.spec is None:
            return None
        matches = [
            field
            for name, field in self.spec.modules.items()
            if callee == name or callee.startswith(f"{name}.")
        ]
        return max(matches, key=lambda field: len(field.name), default=None)

    def _is_torch_call(self, callee: str) -> bool:
        canonical = self.callables.canonical_callee(self.execution.path, callee)
        return canonical == "torch" or canonical.startswith("torch.")

    def _meaningful_function(
        self, callee: str, resolution: ProjectCallResolution
    ) -> bool:
        suffix = callee.rsplit(".", 1)[-1].lower()
        if callee.startswith("super.") and suffix == "forward":
            return True
        if callee.startswith("self.") and suffix not in _TRANSPARENT_CALLS:
            return True
        if suffix in _TRANSPARENT_CALLS:
            return False
        if self._is_torch_call(callee):
            return True
        if resolution.target is not None or resolution.unresolved_reason is not None:
            return True
        return any(token in suffix for token in _MEANINGFUL_CALL_TOKENS)

    def _add_unresolved_call(
        self,
        node: ast.Call,
        callee: str,
        reason: str,
        inputs: list[str],
        previous: str | None,
    ) -> str:
        node_id = self.add_node(
            node,
            label=f"未解析调用: {callee}",
            kind="operation",
            op="unresolved_call",
            description=f"无法静态解析调用 {callee}：{reason}。",
            metadata={
                "component_symbol_id": None,
                "expandable": False,
                "external": True,
            },
        )
        for source in inputs or ([previous] if previous else []):
            self.add_edge(source, node_id)
        return node_id

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
            callee = _static_callee_name(node.func) or "dynamic_call"
            field = self._field_for_callee(callee)
            resolution = self.callables.resolve(self.execution, callee)
            if field is None and not self._meaningful_function(callee, resolution):
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
            elif resolution.unresolved_reason is not None:
                return self._add_unresolved_call(
                    node,
                    callee,
                    resolution.unresolved_reason,
                    inputs,
                    previous,
                )
            elif resolution.target is not None:
                target = resolution.target
                node_id = self.add_node(
                    node,
                    label=_display_name(callee.rsplit(".", 1)[-1]),
                    kind="component",
                    op="function",
                    description=f"调用项目函数 {target.root_label}。",
                    metadata={
                        "constructor": callee,
                        "component_symbol_id": target.root_symbol,
                        "expandable": target.root_symbol in self.callables.by_symbol,
                        "external": False,
                    },
                )
            else:
                label = _display_name(callee.rsplit(".", 1)[-1])
                internal_method = (
                    self.spec is not None
                    and callee.startswith("self.")
                    and callee.rsplit(".", 1)[-1] in self.spec.methods
                )
                node_id = self.add_node(
                    node,
                    label=label,
                    kind="operation" if self._is_torch_call(callee) else "component",
                    op=(
                        self.callables.canonical_callee(self.execution.path, callee)
                        if self._is_torch_call(callee)
                        else "function"
                    ),
                    description=(
                        f"本地静态分析识别的张量操作：{callee}。"
                        if self._is_torch_call(callee)
                        else f"模型主路径中的关键外部调用：{callee}。"
                    ),
                    metadata={
                        "constructor": callee,
                        "component_symbol_id": None,
                        "expandable": False,
                        "external": not internal_method,
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
                    description=f"{self.execution.root_label} 的输出。",
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
                description=f"{self.execution.root_label} 的输入参数 {argument.arg}。",
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
                description=f"{self.execution.root_label} 的输出。",
                metadata={"expandable": False, "external": False},
            )
            self.add_edge(previous, output)
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "root_symbol": self.execution.root_symbol,
            "root_label": self.execution.root_label,
            "execution_symbol": self.execution_symbol,
        }


def build_architecture_index(
    sources: list[tuple[str, str, ast.Module]],
    symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    classes = _collect_classes(sources)
    imports_by_path = {
        path: _import_bindings(path, tree)
        for path, _source, tree in sources
    }
    executions: list[ExecutionSpec] = []
    for spec in classes.values():
        delegated = _delegated_execution_method(spec)
        executions.append(
            ExecutionSpec(
                root_symbol=spec.symbol_id,
                execution_symbol=f"{spec.path}::{spec.name}.{delegated.name}",
                root_label=spec.name,
                path=spec.path,
                function=delegated,
                owner=spec,
            )
        )
        for method_name, method in spec.methods.items():
            if method_name == "__init__":
                continue
            executions.append(
                ExecutionSpec(
                    root_symbol=f"{spec.path}::{spec.name}.{method_name}",
                    execution_symbol=f"{spec.path}::{spec.name}.{method_name}",
                    root_label=f"{spec.name}.{method_name}",
                    path=spec.path,
                    function=method,
                    owner=spec,
                )
            )
    for path, _source, tree in sources:
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            symbol_id = f"{path}::{node.name}"
            executions.append(
                ExecutionSpec(
                    root_symbol=symbol_id,
                    execution_symbol=symbol_id,
                    root_label=node.name,
                    path=path,
                    function=node,
                )
            )
    callables = ProjectCallableIndex(executions, imports_by_path)

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
        execution.root_symbol: ArchitectureGraphBuilder(execution, classes, callables).build()
        for execution in executions
    }
    return {
        "default_root": roots[0]["symbol_id"] if roots else None,
        "roots": roots,
        "graphs": graphs,
    }
