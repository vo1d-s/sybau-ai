"""Python tooling utilities: syntax checking, symbol listing, and test running.

This module provides three main capabilities:
  1. check_syntax        - parse a file with `ast` to validate syntax.
  2. list_symbols        - walk a project directory and list top-level
                           functions/classes per file.
  3. run_tests           - run pytest (preferred) or unittest discovery.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Iterable, Iterator


# ---------------------------------------------------------------------------
# Syntax checking
# ---------------------------------------------------------------------------

@dataclass
class SyntaxIssue:
    path: str
    line: int | None
    column: int | None
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        loc = f"{self.line}:{self.column}" if self.line is not None else "?"
        return f"{self.path}:{loc} {self.message}"


def check_syntax(path: str) -> list[SyntaxIssue]:
    """Return a list of syntax issues for a single Python file.

    An empty list means the file parsed successfully.
    """
    if not os.path.isfile(path):
        return [SyntaxIssue(path, None, None, "file not found")]
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        return [SyntaxIssue(path, None, None, f"read error: {exc}")]

    try:
        ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [SyntaxIssue(path, exc.lineno, exc.offset, exc.msg)]
    return []


def check_syntax_tree(root: str) -> list[SyntaxIssue]:
    """Recursively check every .py file under `root`."""
    issues: list[SyntaxIssue] = []
    for py_file in _iter_python_files(root):
        issues.extend(check_syntax(py_file))
    return issues


# ---------------------------------------------------------------------------
# Symbol listing
# ---------------------------------------------------------------------------

@dataclass
class FileSymbols:
    path: str
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)


def list_symbols(path: str) -> FileSymbols:
    """List top-level functions and classes defined in a Python file."""
    result = FileSymbols(path=path)
    if not os.path.isfile(path):
        return result
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError):
        return result

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            result.classes.append(node.name)
    return result


def list_symbols_tree(root: str) -> list[FileSymbols]:
    """Run `list_symbols` across every .py file under `root`."""
    return [list_symbols(p) for p in _iter_python_files(root)]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    runner: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_tests(root: str = ".", prefer: str = "pytest") -> TestResult:
    """Run the project's test suite.

    Tries `pytest` first (if available and `prefer == 'pytest'`), then falls
    back to `python -m unittest discover`.
    """
    if prefer == "pytest" and _has_module("pytest"):
        cmd = [sys.executable, "-m", "pytest", root]
        runner = "pytest"
    else:
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", root]
        runner = "unittest"

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return TestResult(
        runner=runner,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}


def _iter_python_files(root: str) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
