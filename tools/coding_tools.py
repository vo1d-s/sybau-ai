import ast
import subprocess
import re
from pathlib import Path
from .registry import register_tool, ToolError


# ----------------------------
# READ PYTHON STRUCTURE (AST)
# ----------------------------
@register_tool("analyze_python", "Analyze Python file structure (functions, classes, imports)")
def analyze_python(args: dict) -> str:
    path = args.get("path")

    if not path:
        raise ToolError("Missing path")

    p = Path(path)

    if not p.exists():
        raise ToolError("File not found")

    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))

        functions = []
        classes = []
        imports = []

        for node in ast.walk(tree):

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)

            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)

            elif isinstance(node, ast.Import):
                for n in node.names:
                    imports.append(n.name)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)

        return (
            f"Functions: {functions}\n"
            f"Classes: {classes}\n"
            f"Imports: {imports}"
        )

    except Exception as e:
        raise ToolError(str(e))


# ----------------------------
# FORMAT CODE (BLACK-LIKE)
# ----------------------------
@register_tool("format_python", "Auto-format Python code using built-in formatting")
def format_python(args: dict) -> str:
    path = args.get("path")

    if not path:
        raise ToolError("Missing path")

    p = Path(path)

    if not p.exists():
        raise ToolError("File not found")

    code = p.read_text(encoding="utf-8")

    # Validate syntax first so we never overwrite a file we can't parse.
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise ToolError(f"Cannot format file with syntax error: {e}")

    # Prefer black if installed; otherwise fall back to ast.unparse which
    # at least produces canonical, parseable Python (but loses comments).
    formatted: str
    used: str
    try:
        import black  # type: ignore
        try:
            formatted = black.format_str(code, mode=black.Mode())
            used = "black"
        except Exception as e:
            raise ToolError(f"black failed: {e}")
    except ImportError:
        # ast.unparse is lossy (drops comments) -- refuse rather than corrupt.
        raise ToolError(
            "format_python requires the 'black' package. Install it with "
            "'pip install black' or skip formatting."
        )

    # Preserve a single trailing newline (POSIX), no aggressive .strip().
    if not formatted.endswith("\n"):
        formatted += "\n"

    p.write_text(formatted, encoding="utf-8")
    return f"Formatted {path} using {used}"


# ----------------------------
# RUN PYTHON FILE SAFELY
# ----------------------------
@register_tool("run_python", "Run a Python file and return output")
def run_python(args: dict) -> str:
    path = args.get("path")

    if not path:
        raise ToolError("Missing path")

    timeout = float(args.get("timeout", 30))

    try:
        result = subprocess.run(
            ["python", path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return result.stdout + result.stderr

    except subprocess.TimeoutExpired as e:
        partial = ""
        if e.stdout:
            partial += e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", "ignore")
        if e.stderr:
            partial += e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", "ignore")
        return f"[timeout after {timeout}s]\n{partial}"


# ----------------------------
# FIND CODE PATTERN
# ----------------------------
@register_tool("search_code", "Search text inside codebase")
def search_code(args: dict) -> str:
    root = args.get("path", ".")
    query = args.get("query")

    if not query:
        raise ToolError("Missing query")

    matches = []

    for p in Path(root).rglob("*.*"):

        try:
            text = p.read_text(encoding="utf-8", errors="ignore")

            if query.lower() in text.lower():
                matches.append(str(p))

        except:
            continue

    return "\n".join(matches) if matches else "No matches"


# ----------------------------
# SIMPLE REFACTOR HELP (rename symbol)
# ----------------------------
@register_tool("rename_symbol", "Rename variable/function in file (simple replace)")
def rename_symbol(args: dict) -> str:
    path = args.get("path")
    old = args.get("old")
    new = args.get("new")

    if not all([path, old, new]):
        raise ToolError("Missing args")

    p = Path(path)

    if not p.exists():
        raise ToolError("File not found")

    # Validate that old/new are valid Python identifiers -- otherwise the
    # word-boundary regex below would still match, but the result is almost
    # certainly not what the caller intended.
    if not old.isidentifier():
        raise ToolError(f"'old' must be a valid Python identifier, got: {old!r}")
    if not new.isidentifier():
        raise ToolError(f"'new' must be a valid Python identifier, got: {new!r}")

    content = p.read_text(encoding="utf-8")

    # Match the identifier only when surrounded by non-identifier characters.
    # This avoids matching `old` inside `older`, but still touches strings
    # and comments -- callers should review the diff.
    pattern = re.compile(rf"\b{re.escape(old)}\b")
    updated, count = pattern.subn(new, content)

    if count == 0:
        return f"No occurrences of {old!r} found in {path}"

    # If the file was valid Python before, make sure it's still valid after.
    if path.endswith(".py"):
        try:
            ast.parse(content)
            try:
                ast.parse(updated)
            except SyntaxError as e:
                raise ToolError(
                    f"Rename would produce invalid Python ({e}); aborting."
                )
        except SyntaxError:
            # Original was already broken; don't block the rename.
            pass

    p.write_text(updated, encoding="utf-8")
    return f"Replaced {count} occurrence(s) of {old} → {new} in {path}"