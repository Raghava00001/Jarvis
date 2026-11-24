"""
Every self.method(...) call must name something the class defines.

pyflakes can't see these. A call to a missing self._broadcast() in the news
path threw away every news reply (AttributeError), and the AI answered instead.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _defined_in(cls):
    defined = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in cls.body:
        if isinstance(n, ast.Assign):
            defined |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    for n in ast.walk(cls):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "self" and isinstance(n.ctx, ast.Store)):
            defined.add(n.attr)
    return defined


def _calls_missing(path, cls, defined):
    out = []
    for n in ast.walk(cls):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
                and n.func.attr not in defined):
            out.append(f"{path.relative_to(ROOT)}:{n.lineno} {cls.name}.{n.func.attr}()")
    return out


def _server_parts():
    """JARVISWebSocketServer is split into mixins (jarvis/gui/server/) that call
    each other's methods: check them together, against everything they define."""
    files = [ROOT / "jarvis/gui/websocket_server.py"] + sorted((ROOT / "jarvis/gui/server").glob("*.py"))
    parts = [(f, c) for f in files for c in ast.walk(ast.parse(f.read_text(encoding="utf-8-sig")))
             if isinstance(c, ast.ClassDef)]
    return files, parts


def test_server_parts_only_call_methods_the_server_has():
    files, parts = _server_parts()
    assert len(parts) >= 11  # the server and its ten mixins
    defined = set().union(*(_defined_in(c) for _, c in parts))
    missing = [m for f, c in parts for m in _calls_missing(f, c, defined)]
    assert missing == [], "\n".join(missing)


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
        if path in _server_parts()[0]:
            continue  # checked as one class above
        missing += _missing_self_calls(path)
    assert missing == [], "\n".join(missing)
