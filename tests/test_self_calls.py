"""
Every self.method(...) call must name something the class defines.

pyflakes can't see these. A call to a missing self._broadcast() in the news
path threw away every news reply (AttributeError), and the AI answered instead.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _missing_self_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    out = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        if cls.bases and any(getattr(b, "id", getattr(b, "attr", "")) not in ("object",) for b in cls.bases):
            continue  # inherited methods: can't tell statically
        defined = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for n in cls.body:
            if isinstance(n, ast.Assign):
                defined |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(cls):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "self" and isinstance(n.ctx, ast.Store)):
                defined.add(n.attr)
        for n in ast.walk(cls):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
                    and n.func.attr not in defined):
                out.append(f"{path.relative_to(ROOT)}:{n.lineno} {cls.name}.{n.func.attr}()")
    return out


def test_no_calls_to_undefined_methods():
    missing = []
    for path in sorted((ROOT / "jarvis").rglob("*.py")):
        if "experimental" in path.parts:
            continue
        missing += _missing_self_calls(path)
    assert missing == [], "\n".join(missing)
