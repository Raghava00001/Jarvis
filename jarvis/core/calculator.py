"""
Spoken arithmetic: "calculate 25 times 4", "what is 15 percent of 200",
"square root of 81", "12.5 divided by 4".

"calculate 25 times 4" used to be answered with the current time ("times"
contains "time"). Expressions are evaluated with a tiny AST walker that only
allows numbers and + - * / // % ** and parentheses: never eval().
"""

import ast
import logging
import math
import operator
import re
from typing import Optional

_log = logging.getLogger(__name__)

_WORDS = [
    (r"\bmultiplied by\b|\btimes\b|\bx\b|×", "*"),
    (r"\bdivided by\b|\bover\b|÷", "/"),
    (r"\bplus\b|\badd\b", "+"),
    (r"\bminus\b|\bsubtract\b|\bless\b", "-"),
    (r"\bto the power of\b|\braised to\b|\^", "**"),
    (r"\bmod(?:ulo)?\b", "%"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
]

_LEAD = re.compile(r"^(?:hey |ok )?(?:jarvis[, ]+)?(?:please |can you |could you )*"
                   r"(?:calculate|compute|work out|solve|evaluate|what(?:'s| is)|how much is)?\s*", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(\d+(?:\.\d+)?)", re.I)
_SQRT = re.compile(r"(?:the\s+)?square root of\s+(\d+(?:\.\d+)?)", re.I)
_ALLOWED = re.compile(r"^[\d\s.+\-*/%()]+$")

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def expression_from(text: str) -> Optional[str]:
    """The arithmetic expression in a spoken request, or None if it isn't one."""
    t = (text or "").lower().strip().rstrip("?.! ")
    t = _LEAD.sub("", t, count=1)
    t = _PERCENT.sub(lambda m: f"({m.group(1)}/100*{m.group(2)})", t)
    t = _SQRT.sub(lambda m: f"({m.group(1)})**0.5", t)
    for pattern, op in _WORDS:
        t = re.sub(pattern, f" {op} ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or not _ALLOWED.match(t):
        return None
    # at least one operator between numbers ("2026" alone is not a calculation)
    if not re.search(r"\d\s*(?:\*\*|[+\-*/%])\s*[\d(]|\)\s*(?:\*\*|[+\-*/%])|\*\*\s*0\.5|\)\s*\*\*", t):
        return None
    return t


def evaluate(expr: str) -> float:
    """Evaluate an expression from expression_from(). Raises ValueError if it isn't safe."""
    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            left, right = walk(n.left), walk(n.right)
            if isinstance(n.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
                raise ValueError("exponent too large")
            return _OPS[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](walk(n.operand))
        raise ValueError(f"not allowed: {type(n).__name__}")
    return walk(ast.parse(expr, mode="eval"))


def format_number(x: float) -> str:
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return "undefined"
    if float(x).is_integer() and abs(x) < 1e15:
        return f"{int(x):,}"
    return f"{x:,.6g}" if abs(x) < 1e6 else f"{x:.6g}"


def answer(text: str) -> Optional[str]:
    """The result of a spoken calculation, e.g. '100', or None if it isn't one."""
    expr = expression_from(text)
    if expr is None:
        return None
    try:
        return format_number(evaluate(expr))
    except ZeroDivisionError:
        return "undefined (division by zero)"
    except (ValueError, SyntaxError, OverflowError) as e:
        _log.debug(f"[CALC] Couldn't evaluate {expr!r}: {e}")
        return None
