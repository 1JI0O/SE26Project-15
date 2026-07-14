import ast
from collections.abc import Iterable
from typing import Any

from app.services.code_analysis.python_ast import expression_name


def _operator_name(operator: ast.operator) -> str:
    return {
        ast.Add: "add",
        ast.Sub: "subtract",
        ast.Mult: "multiply",
        ast.Div: "divide",
        ast.MatMult: "matmul",
    }.get(type(operator), operator.__class__.__name__.lower())


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [expression_name(target)]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for item in target.elts for name in _target_names(item)]
    return []


def _iter_forward_methods(
    tree: ast.Module,
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            is_function = isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            if is_function and child.name == "forward":
                yield f"{node.name}.forward", child


def _collect_module_specs(
    sources: list[tuple[str, str, ast.Module]],
) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for path, _source, tree in sources:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            callee = expression_name(value.func)
            for target in targets:
                for name in _target_names(target):
                    if not name.startswith("self."):
                        continue
                    specs[f"{path}::{name}"] = {
                        "constructor": callee,
                        "components": [
                            expression_name(argument.func)
                            for argument in value.args
                            if isinstance(argument, ast.Call)
                        ],
                    }
    return specs


class ForwardGraphBuilder:
    def __init__(
        self,
        path: str,
        qualified_name: str,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        module_specs: dict[str, dict[str, Any]],
        symbols: list[dict[str, Any]],
    ) -> None:
        self.path = path
        self.function = function
        self.symbol_id = f"{path}::{qualified_name}"
        self.module_specs = module_specs
        self.symbols = symbols
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.environment: dict[str, str] = {}
        self.counter = 0

    def add_node(
        self,
        node: ast.AST,
        *,
        op: str,
        label: str,
        kind: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.counter += 1
        line_start = getattr(node, "lineno", self.function.lineno)
        line_end = getattr(node, "end_lineno", line_start) or line_start
        node_id = f"{self.symbol_id}#{line_start}:{getattr(node, 'col_offset', 0)}:{self.counter}"
        self.nodes.append(
            {
                "id": node_id,
                "op": op,
                "label": label,
                "kind": kind,
                "description": description,
                "symbol_id": self.symbol_id,
                "shape": None,
                "shape_reason": "Static analysis cannot determine runtime tensor dimensions",
                "source_path": self.path,
                "line_start": line_start,
                "line_end": line_end,
                "metadata": metadata or {},
            }
        )
        return node_id

    def add_edge(self, source: str | None, target: str, kind: str = "tensor") -> None:
        if not source or source == target:
            return
        edge_id = f"e{len(self.edges) + 1}:{source}->{target}:{kind}"
        if any(
            edge["source"] == source and edge["target"] == target and edge["kind"] == kind
            for edge in self.edges
        ):
            return
        self.edges.append(
            {"id": edge_id, "source": source, "target": target, "kind": kind, "label": kind}
        )

    def _resolved_symbol(self, callee: str) -> str | None:
        candidate = callee.rsplit(".", 1)[-1]
        matches = [
            str(symbol["id"])
            for symbol in self.symbols
            if symbol.get("kind") == "class" and symbol.get("name") == candidate
        ]
        return matches[0] if len(matches) == 1 else None

    def expression(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.environment.get(node.id)
        if isinstance(node, ast.Attribute):
            return self.environment.get(expression_name(node))
        if isinstance(node, ast.Constant):
            return None
        if isinstance(node, ast.Call):
            inputs = [self.expression(argument) for argument in node.args]
            inputs.extend(self.expression(keyword.value) for keyword in node.keywords)
            callee = expression_name(node.func) or "dynamic_call"
            module_spec = self.module_specs.get(f"{self.path}::{callee}")
            is_concat = callee in {"torch.cat", "torch.concat", "torch.stack"}
            op = "concatenate" if is_concat else "sequential" if module_spec else callee
            kind = "merge" if is_concat else "operation"
            metadata: dict[str, Any] = {"callee": callee}
            if module_spec:
                metadata["sequential_components"] = module_spec["components"]
            symbol_name = module_spec["constructor"] if module_spec else callee
            resolved_symbol_id = self._resolved_symbol(symbol_name)
            if resolved_symbol_id:
                metadata["resolved_symbol_id"] = resolved_symbol_id
            graph_node = self.add_node(
                node,
                op=op,
                label=callee,
                kind=kind,
                description=f"Tensor operation inferred from call to {callee}.",
                metadata=metadata,
            )
            for source in inputs:
                self.add_edge(source, graph_node)
            return graph_node
        if isinstance(node, ast.BinOp):
            left = self.expression(node.left)
            right = self.expression(node.right)
            op = _operator_name(node.op)
            graph_node = self.add_node(
                node,
                op=op,
                label=op,
                kind="merge" if op in {"add", "subtract"} else "operation",
                description=f"Tensor {op} operation inferred from a binary expression.",
            )
            self.add_edge(left, graph_node)
            self.add_edge(right, graph_node)
            return graph_node
        if isinstance(node, ast.UnaryOp):
            return self.expression(node.operand)
        if isinstance(node, ast.Subscript):
            return self.expression(node.value)
        if isinstance(node, ast.Tuple | ast.List):
            values = [self.expression(item) for item in node.elts]
            values = [value for value in values if value]
            if len(values) == 1:
                return values[0]
            if values:
                graph_node = self.add_node(
                    node,
                    op="pack",
                    label="tensor collection",
                    kind="merge",
                    description="Multiple tensor values are grouped into a collection.",
                )
                for source in values:
                    self.add_edge(source, graph_node)
                return graph_node
        return None

    def statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assign):
                value_node = self.expression(statement.value)
                for target in statement.targets:
                    for name in _target_names(target):
                        if value_node:
                            self.environment[name] = value_node
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                value_node = self.expression(statement.value)
                for name in _target_names(statement.target):
                    if value_node:
                        self.environment[name] = value_node
            elif isinstance(statement, ast.AugAssign):
                target_name = expression_name(statement.target)
                left = self.environment.get(target_name)
                right = self.expression(statement.value)
                op = _operator_name(statement.op)
                merge = self.add_node(
                    statement,
                    op=op,
                    label=f"{target_name} {op}",
                    kind="merge",
                    description=f"In-place tensor {op} merges two data-flow branches.",
                )
                self.add_edge(left, merge, "residual")
                self.add_edge(right, merge, "residual")
                if target_name:
                    self.environment[target_name] = merge
            elif isinstance(statement, ast.Expr):
                self.expression(statement.value)
            elif isinstance(statement, ast.If):
                self._if_statement(statement)
            elif isinstance(statement, ast.Return):
                source = self.expression(statement.value) if statement.value else None
                output = self.add_node(
                    statement,
                    op="return",
                    label="return",
                    kind="output",
                    description="Forward method tensor output.",
                )
                self.add_edge(source, output)

    def _if_statement(self, statement: ast.If) -> None:
        condition = ast.unparse(statement.test)
        condition_source = self.expression(statement.test)
        branch = self.add_node(
            statement.test,
            op="branch",
            label=condition,
            kind="branch",
            description=f"Control-flow branch: {condition}.",
        )
        self.add_edge(condition_source, branch, "control")
        before = self.environment.copy()
        before_node_count = len(self.nodes)
        self.statements(statement.body)
        body_environment = self.environment.copy()
        for node in self.nodes[before_node_count:]:
            self.add_edge(branch, node["id"], "control")

        self.environment = before.copy()
        else_node_count = len(self.nodes)
        self.statements(statement.orelse)
        else_environment = self.environment.copy()
        for node in self.nodes[else_node_count:]:
            self.add_edge(branch, node["id"], "control")

        merged = before.copy()
        for name in sorted(body_environment.keys() | else_environment.keys()):
            body_value = body_environment.get(name, before.get(name))
            else_value = else_environment.get(name, before.get(name))
            if body_value and else_value and body_value != else_value:
                merge = self.add_node(
                    statement,
                    op="branch_merge",
                    label=f"merge {name}",
                    kind="merge",
                    description=f"Merges tensor {name} after conditional branches.",
                )
                self.add_edge(body_value, merge, "branch")
                self.add_edge(else_value, merge, "branch")
                merged[name] = merge
            elif body_value or else_value:
                merged[name] = body_value or else_value  # type: ignore[assignment]
        self.environment = merged

    def build(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        for argument in self.function.args.args:
            if argument.arg == "self":
                continue
            input_node = self.add_node(
                argument,
                op="input",
                label=argument.arg,
                kind="input",
                description=f"Input parameter {argument.arg} of the forward method.",
            )
            self.environment[argument.arg] = input_node
        self.statements(self.function.body)
        return self.nodes, self.edges


def build_tensor_graph(
    sources: list[tuple[str, str, ast.Module]],
    symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    module_specs = _collect_module_specs(sources)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    forward_symbols: list[str] = []
    for path, _source, tree in sources:
        for qualified_name, function in _iter_forward_methods(tree):
            builder = ForwardGraphBuilder(
                path,
                qualified_name,
                function,
                module_specs,
                symbols,
            )
            method_nodes, method_edges = builder.build()
            nodes.extend(method_nodes)
            edges.extend(method_edges)
            forward_symbols.append(builder.symbol_id)
    return {
        "nodes": nodes,
        "edges": edges,
        "entry_symbols": forward_symbols,
        "shape_status": "unknown",
        "shape_reason": "Runtime shape propagation was not requested or is unavailable",
    }
