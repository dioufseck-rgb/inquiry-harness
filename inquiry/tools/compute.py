"""
The arithmetic instrument.

A computation takes numbers extracted from evidence items, evaluates an
expression over them, and yields a result. The harness turns that into a
model_output evidence item whose provenance records the expression, the
inputs and their evidence ids, so the result is reproducible from the graph
alone. This is the smallest instrument: it lets the harness notice that two
estimates are compatible, or that a figure restated on another base agrees,
which no amount of reading does.

Expressions are evaluated on a restricted AST: numbers, named variables,
+ - * / // % **, unary minus, parentheses, and a few functions. No names
other than the declared variables resolve, so nothing else can run.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS: dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "round": round, "sqrt": math.sqrt, "log": math.log, "exp": math.exp,
}

INSTRUMENT_VERSION = "arithmetic/1"


class ComputeError(ValueError):
    pass


def safe_eval(expression: str, variables: dict[str, float]) -> float:
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise ComputeError(f"cannot parse {expression!r}: {e.msg}") from e

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ComputeError(f"unknown variable {node.id!r}")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return float(_FUNCS[node.func.id](*(ev(a) for a in node.args)))
        raise ComputeError(f"disallowed syntax in {expression!r}: {type(node).__name__}")

    try:
        out = ev(tree)
    except ZeroDivisionError as e:
        raise ComputeError(f"division by zero in {expression!r}") from e
    if math.isnan(out) or math.isinf(out):
        raise ComputeError(f"{expression!r} is not finite")
    return out
