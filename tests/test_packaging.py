"""The release build must not leave out a module the app imports."""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _excludes():
    spec = open(os.path.join(ROOT, "packaging", "common.spec.py"), encoding="utf-8").read()
    block = re.search(r"EXCLUDES = \[(.*?)\]", spec, re.S).group(1)
    return set(re.findall(r'"([\w.]+)"', block))


def _imports():
    names = set()
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "src", "handtrack")):
        for f in files:
            if f.endswith(".py"):
                tree = ast.parse(open(os.path.join(folder, f), encoding="utf-8").read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names.update(a.name for a in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                        names.add(node.module)
    return names


def test_no_imported_module_is_excluded_from_the_build():
    excluded = _excludes()
    used = {m for m in _imports() if any(m == e or m.startswith(e + ".") for e in excluded)}
    # matplotlib is imported only to be stubbed out (see engine._stub_matplotlib).
    assert used <= {"matplotlib"}, f"excluded from the build but imported: {sorted(used)}"
