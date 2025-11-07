#!/usr/bin/env python3
"""Generate a JSON snapshot of API routes declared in the repository.

The script walks all project Python files (excluding virtual environments and
other build artifacts), looking for function decorators such as
``@router.get("/path")`` or ``@api_bp.route("/path", methods=["GET"])``.
It records the decorator prefix (e.g. ``router``), the decorator method, the
resolved path expression, and any explicit HTTP method list. The resulting data
is written to ``artifacts/api_routes.json`` by default.
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DEFAULT = REPO_ROOT / "artifacts" / "api_routes.json"

# Directory names that should be skipped entirely when walking the tree.
SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "thesis_venv",
    "__pycache__",
    "output",
    "presentation_assets",
    "thesis_results",
}

# Decorator attribute names that identify route registrations we care about.
ROUTE_ATTRS = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "options",
    "head",
    "route",
    "api_route",
}


@dataclass
class RouteRecord:
    file: Path
    function: str
    decorator_prefix: str
    decorator_method: str
    path: Optional[str]
    methods: Optional[List[str]]

    def as_dict(self) -> dict:
        return {
            "file": self.file.as_posix(),
            "function": self.function,
            "decorator_prefix": self.decorator_prefix,
            "decorator_method": self.decorator_method,
            "path": self.path,
            "methods": self.methods,
        }


class RouteCollector(ast.NodeVisitor):
    """Collect route decorator metadata from a single module."""

    def __init__(self, module_path: Path, source: str) -> None:
        self.module_path = module_path
        self.source = source
        self.routes: list[RouteRecord] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._record_routes(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(  # noqa: N802
        self, node: ast.AsyncFunctionDef
    ) -> None:
        self._record_routes(node)
        self.generic_visit(node)

    def _record_routes(self, node: ast.AST) -> None:
        for decorator in getattr(node, "decorator_list", []):
            record = self._parse_decorator(decorator, node)
            if record is not None:
                self.routes.append(record)

    def _parse_decorator(
        self, decorator: ast.AST, node: ast.AST
    ) -> Optional[RouteRecord]:
        if not isinstance(decorator, ast.Call):
            return None

        func = decorator.func
        if not isinstance(func, ast.Attribute):
            return None

        method = func.attr
        if method not in ROUTE_ATTRS:
            return None

        prefix = dotted_name(func.value)
        if prefix is None:
            return None

        path_value = resolve_path_expression(decorator)
        methods = resolve_methods(decorator, method)

        rel_path = self.module_path.relative_to(REPO_ROOT)
        return RouteRecord(
            file=rel_path,
            function=getattr(node, "name", "<lambda>"),
            decorator_prefix=prefix,
            decorator_method=method,
            path=path_value,
            methods=methods,
        )


def dotted_name(node: ast.AST) -> Optional[str]:
    """Return a dotted string for ``node`` if composed of Name/Attribute."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def resolve_path_expression(call: ast.Call) -> Optional[str]:
    """Resolve the route path expression from positional/keyword args."""

    if call.args:
        value = call.args[0]
        result = expression_to_str(value)
        if result is not None:
            return result

    for kw in call.keywords:
        if kw.arg == "path":
            return expression_to_str(kw.value)

    return None


def resolve_methods(call: ast.Call, decorator_method: str) -> Optional[List[str]]:
    """Resolve an explicit methods list or infer from decorator name."""

    for kw in call.keywords:
        if kw.arg != "methods":
            continue
        value = kw.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            methods: list[str] = []
            for element in value.elts:
                text = expression_to_str(element)
                if text is not None:
                    methods.append(text.upper())
            return methods or None
        text = expression_to_str(value)
        if text is not None:
            return [text.upper()]

    if decorator_method != "route":
        return [decorator_method.upper()]
    return None


def expression_to_str(node: ast.AST) -> Optional[str]:
    """Best-effort conversion of an AST expression to a string."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    try:
        return ast.unparse(node)  # Python 3.9+
    except Exception:  # pragma: no cover - extremely uncommon
        return None


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def collect_routes(paths: Iterable[Path]) -> List[RouteRecord]:
    records: list[RouteRecord] = []
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Skip files that are not valid UTF-8 (unlikely in source tree).
            continue
        tree = ast.parse(source, filename=str(path))
        collector = RouteCollector(module_path=path, source=source)
        collector.visit(tree)
        records.extend(collector.routes)
    records.sort(key=lambda r: (r.file.as_posix(), r.function))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Path for the generated JSON snapshot (default: artifacts/api_routes.json)",
    )
    args = parser.parse_args()

    routes = collect_routes(iter_python_files(REPO_ROOT))
    data = [route.as_dict() for route in routes]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(data)} routes to {args.output}")


if __name__ == "__main__":
    main()
