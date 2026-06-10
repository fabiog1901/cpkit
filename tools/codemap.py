#!/usr/bin/env python3
"""Generate deterministic code maps for Python projects."""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GENERATED_MARKER = "<!-- GENERATED FILE: DO NOT EDIT -->"
SKIP_DIRS = {
    ".archive",
    ".build",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "site",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@dataclass(frozen=True)
class ImportInfo:
    module: str
    names: list[str] = field(default_factory=list)
    level: int = 0


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    full_path: str
    function: str
    lineno: int
    response_model: str | None = None
    dependencies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    lineno: int
    signature: str
    docstring: str | None
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False


@dataclass(frozen=True)
class ClassInfo:
    name: str
    lineno: int
    docstring: str | None
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionInfo] = field(default_factory=list)


@dataclass(frozen=True)
class ModuleInfo:
    path: str
    module_name: str
    package: str
    docstring: str | None
    imports: list[ImportInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    routes: list[RouteInfo] = field(default_factory=list)
    command_handlers: dict[str, str] = field(default_factory=dict)


def ast_to_str(node: ast.AST | None) -> str:
    """Return a deterministic source-like representation for an AST node."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def literal_string(node: ast.AST | None) -> str | None:
    """Return a string literal value when an AST node is a string constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def rel(root: Path, path: Path) -> str:
    """Return a POSIX relative path."""
    return path.relative_to(root).as_posix()


def load_pyproject(root: Path) -> dict[str, Any]:
    """Load pyproject metadata when present."""
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def project_name(root: Path, pyproject: dict[str, Any]) -> str:
    """Return the package/project name from pyproject metadata."""
    poetry = pyproject.get("tool", {}).get("poetry", {})
    project = pyproject.get("project", {})
    return poetry.get("name") or project.get("name") or root.name


def script_rows(pyproject: dict[str, Any]) -> list[str]:
    """Return deterministic CLI entry point rows."""
    poetry_scripts = pyproject.get("tool", {}).get("poetry", {}).get("scripts", {})
    project_scripts = pyproject.get("project", {}).get("scripts", {})
    scripts = {**project_scripts, **poetry_scripts}
    return [f"- `{name}` -> `{target}`" for name, target in sorted(scripts.items())]


def package_roots(root: Path, pyproject: dict[str, Any]) -> list[Path]:
    """Discover importable package roots for a Python project."""
    poetry = pyproject.get("tool", {}).get("poetry", {})
    roots: set[Path] = set()

    for package in poetry.get("packages", []):
        include = package.get("include")
        if include:
            path = root / include
            if path.exists():
                roots.add(path)

    name_root = root / project_name(root, pyproject).replace("-", "_")
    if name_root.exists():
        roots.add(name_root)

    for path in root.iterdir():
        if path.name in SKIP_DIRS or path.name.startswith("."):
            continue
        if path.is_dir() and (path / "__init__.py").exists():
            roots.add(path)

    return sorted(roots)


def source_roots(root: Path, extra_roots: list[str]) -> list[Path]:
    """Resolve source roots from CLI input or project metadata."""
    pyproject = load_pyproject(root)
    roots = package_roots(root, pyproject)
    for value in extra_roots:
        path = root / value
        if path.exists():
            roots.append(path)
    return sorted(set(roots))


def iter_python_files(roots: list[Path]) -> list[Path]:
    """Return all Python source files under known roots."""
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def module_name_from_path(root: Path, path: Path) -> str:
    """Convert a Python file path under the repo into an import-style name."""
    module_path = path.relative_to(root).with_suffix("")
    if module_path.name == "__init__":
        module_path = module_path.parent
    return ".".join(module_path.parts)


def extract_imports(tree: ast.Module) -> list[ImportInfo]:
    """Extract top-level imports from a module."""
    imports: list[ImportInfo] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.append(
                ImportInfo(
                    module="",
                    names=sorted(alias.name for alias in node.names),
                    level=0,
                )
            )
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                ImportInfo(
                    module=node.module or "",
                    names=sorted(alias.name for alias in node.names),
                    level=node.level,
                )
            )
    return imports


def join_paths(prefix: str, path: str) -> str:
    """Join FastAPI router prefix and route path into one normalized path."""
    if not prefix:
        return path
    if path == "/":
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def extract_router_prefix(tree: ast.Module) -> str:
    """Extract `APIRouter(prefix=...)` when a module defines a router."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "router"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if ast_to_str(node.value.func) != "APIRouter":
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "prefix":
                return literal_string(keyword.value) or ""
    return ""


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a readable signature for a function without importing it."""
    args = ast_to_str(node.args)
    returns = f" -> {ast_to_str(node.returns)}" if node.returns else ""
    return f"{node.name}({args}){returns}"


def decorator_strings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return decorators as source-like strings."""
    return [ast_to_str(decorator) for decorator in node.decorator_list]


def public_function_info(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> FunctionInfo | None:
    """Return function metadata for public functions and methods."""
    if node.name.startswith("_"):
        return None
    return FunctionInfo(
        name=node.name,
        lineno=node.lineno,
        signature=function_signature(node),
        docstring=ast.get_docstring(node),
        decorators=decorator_strings(node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def extract_classes(tree: ast.Module) -> list[ClassInfo]:
    """Extract public classes and their public methods."""
    classes: list[ClassInfo] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        methods = [
            info
            for item in node.body
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            for info in [public_function_info(item)]
            if info is not None
        ]
        classes.append(
            ClassInfo(
                name=node.name,
                lineno=node.lineno,
                docstring=ast.get_docstring(node),
                bases=[ast_to_str(base) for base in node.bases],
                methods=methods,
            )
        )
    return classes


def extract_functions(tree: ast.Module) -> list[FunctionInfo]:
    """Extract public top-level functions."""
    return [
        info
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for info in [public_function_info(node)]
        if info is not None
    ]


def route_from_decorator(
    decorator: ast.AST,
    function_name: str,
    lineno: int,
    router_prefix: str,
) -> RouteInfo | None:
    """Extract FastAPI route metadata from `@router.<method>(...)` decorators."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in HTTP_METHODS:
        return None
    if ast_to_str(func.value) != "router":
        return None

    route_path = literal_string(decorator.args[0]) if decorator.args else None
    if route_path is None:
        return None

    keyword_map = {kw.arg: kw.value for kw in decorator.keywords if kw.arg}
    response_model = ast_to_str(keyword_map.get("response_model")) or None
    dependencies = []
    responses = keyword_map.get("dependencies")
    if isinstance(responses, ast.List):
        dependencies = [ast_to_str(item) for item in responses.elts]

    return RouteInfo(
        method=func.attr.upper(),
        path=route_path,
        full_path=join_paths(router_prefix, route_path),
        function=function_name,
        lineno=lineno,
        response_model=response_model,
        dependencies=dependencies,
    )


def extract_routes(tree: ast.Module) -> list[RouteInfo]:
    """Extract FastAPI routes from public top-level route handlers."""
    routes: list[RouteInfo] = []
    router_prefix = extract_router_prefix(tree)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            route = route_from_decorator(
                decorator,
                node.name,
                node.lineno,
                router_prefix,
            )
            if route is not None:
                routes.append(route)
    return routes


def extract_command_handlers(tree: ast.Module) -> dict[str, str]:
    """Extract `COMMAND_HANDLERS` mappings from worker dispatch modules."""
    handlers: dict[str, str] = {}
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "COMMAND_HANDLERS"
                for target in node.targets
            ):
                value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "COMMAND_HANDLERS"
        ):
            value = node.value

        if value is None or not isinstance(value, ast.Dict):
            continue
        for key, handler in zip(value.keys, value.values, strict=False):
            if key is None:
                continue
            handlers[ast_to_str(key)] = ast_to_str(handler)
    return dict(sorted(handlers.items()))


def parse_python_file(root: Path, path: Path) -> ModuleInfo:
    """Parse one Python file into deterministic metadata."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    module_name = module_name_from_path(root, path)
    return ModuleInfo(
        path=rel(root, path),
        module_name=module_name,
        package=module_name.split(".")[0],
        docstring=ast.get_docstring(tree),
        imports=extract_imports(tree),
        classes=extract_classes(tree),
        functions=extract_functions(tree),
        routes=extract_routes(tree),
        command_handlers=extract_command_handlers(tree),
    )


def scan_project(root: Path, roots: list[Path]) -> list[ModuleInfo]:
    """Scan Python source roots and return sorted module metadata."""
    return [parse_python_file(root, path) for path in iter_python_files(roots)]


def first_sentence(text: str | None) -> str:
    """Return a short docstring summary suitable for tables."""
    if not text:
        return "_No docstring._"
    stripped = " ".join(text.strip().split())
    return stripped.split(". ")[0].rstrip(".") + "."


def route_sort_key(route: dict[str, Any]) -> tuple[str, str, str]:
    """Sort routes by path, method, then handler."""
    return (route["full_path"], route["method"], route["function"])


def build_project_index(
    root: Path, roots: list[Path], modules: list[ModuleInfo]
) -> dict[str, Any]:
    """Build the machine-readable project index consumed by agents."""
    module_dicts = [asdict(module) for module in modules]
    routes = [
        asdict(route) | {"module": module.module_name}
        for module in modules
        for route in module.routes
    ]
    routes = sorted(routes, key=route_sort_key)
    commands = [
        {"command": command, "handler": handler, "module": module.module_name}
        for module in modules
        for command, handler in module.command_handlers.items()
    ]
    commands = sorted(commands, key=lambda row: (row["command"], row["module"]))

    packages: dict[str, dict[str, int]] = {}
    for module in modules:
        stats = packages.setdefault(
            module.package,
            {
                "modules": 0,
                "classes": 0,
                "functions": 0,
                "routes": 0,
            },
        )
        stats["modules"] += 1
        stats["classes"] += len(module.classes)
        stats["functions"] += len(module.functions)
        stats["routes"] += len(module.routes)

    return {
        "schema_version": 1,
        "source_roots": [rel(root, path) for path in roots],
        "packages": dict(sorted(packages.items())),
        "modules": module_dicts,
        "routes": routes,
        "command_handlers": commands,
    }


def render_code_map(
    root: Path, pyproject: dict[str, Any], index: dict[str, Any]
) -> str:
    """Render a deterministic root code map."""
    lines = [
        "# Code Map",
        "",
        GENERATED_MARKER,
        "",
        "This file is a deterministic map of the Python package surface in this repository.",
        "Regenerate it after structural code changes with:",
        "",
        "```bash",
        "python tools/codemap.py --write",
        "```",
        "",
        "## Project",
        "",
        f"- Name: `{project_name(root, pyproject)}`",
        f"- Package roots: {', '.join(f'`{item}`' for item in index['source_roots']) or 'none found'}",
        "",
        "## Entry Points",
        "",
    ]
    lines.extend(script_rows(pyproject) or ["- none found"])
    lines.extend(
        [
            "",
            "## Packages",
            "",
            "| Package | Modules | Classes | Functions | Routes |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for package, stats in index["packages"].items():
        lines.append(
            f"| `{package}` | {stats['modules']} | {stats['classes']} | "
            f"{stats['functions']} | {stats['routes']} |"
        )

    lines.extend(
        [
            "",
            "## API Routes",
            "",
        ]
    )
    if index["routes"]:
        lines.append("| Method | Path | Handler | Response Model |")
        lines.append("| --- | --- | --- | --- |")
        for route in index["routes"]:
            response_model = route["response_model"] or "-"
            lines.append(
                f"| `{route['method']}` | `{route['full_path']}` | "
                f"`{route['module']}.{route['function']}` | `{response_model}` |"
            )
    else:
        lines.append("- none found")

    lines.extend(
        [
            "",
            "## Command Handlers",
            "",
        ]
    )
    if index["command_handlers"]:
        for command in index["command_handlers"]:
            lines.append(
                f"- `{command['command']}` -> `{command['module']}.{command['handler']}`"
            )
    else:
        lines.append("- none found")

    lines.extend(
        [
            "",
            "## Modules",
            "",
            "| File | Public Surface |",
            "| --- | --- |",
        ]
    )
    for module in index["modules"]:
        details = []
        if module["docstring"]:
            details.append(first_sentence(module["docstring"]))
        if module["classes"]:
            details.append(
                "classes: " + ", ".join(cls["name"] for cls in module["classes"])
            )
        if module["functions"]:
            details.append(
                "functions: " + ", ".join(fn["name"] for fn in module["functions"])
            )
        if module["routes"]:
            details.append(f"routes: {len(module['routes'])}")
        if module["command_handlers"]:
            details.append(f"command handlers: {len(module['command_handlers'])}")
        lines.append(
            f"| `{module['path']}` | {'; '.join(details) if details else 'no public surface'} |"
        )

    return "\n".join(lines).rstrip() + "\n"


def json_dumps(data: dict[str, Any]) -> str:
    """Serialize JSON deterministically with a trailing newline."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_or_check(path: Path, content: str, check: bool, root: Path) -> bool:
    """Write a generated file or report it stale in check mode."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing == content:
        return True
    if check:
        print(f"STALE: {rel(root, path)}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"WROTE: {rel(root, path)}")
    return True


def build_outputs(
    root: Path,
    output: Path,
    index_output: Path | None,
    extra_roots: list[str],
) -> dict[Path, str]:
    """Build all generated outputs for the requested project."""
    pyproject = load_pyproject(root)
    roots = source_roots(root, extra_roots)
    modules = scan_project(root, roots)
    index = build_project_index(root, roots, modules)
    outputs = {output: render_code_map(root, pyproject, index)}
    if index_output is not None:
        outputs[index_output] = json_dumps(index)
    return outputs


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write generated outputs")
    mode.add_argument("--check", action="store_true", help="verify generated outputs")
    parser.add_argument("--root", default=".", help="project root; defaults to cwd")
    parser.add_argument("--output", default="CODEMAP.md", help="codemap output path")
    parser.add_argument(
        "--index-output",
        default=".build/project-index.json",
        help="machine-readable project index path; use an empty value to disable",
    )
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="extra source root to scan, relative to --root; can be repeated",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    output = root / args.output
    index_output = root / args.index_output if args.index_output else None

    try:
        outputs = build_outputs(root, output, index_output, args.source_root)
        ok = all(
            write_or_check(path, content, check=args.check, root=root)
            for path, content in outputs.items()
        )
        return 0 if ok else 1
    except SyntaxError as err:
        print(f"ERROR: unable to parse {err.filename}: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
