import asyncio
from tools.registry import TOOL_REGISTRY, ToolError
from utils_files.encoding import decode_b64
from utils_files import toolbar
from pathlib import Path
import re


# Tools that modify the filesystem.
# These are tracked so the toolbar can show line diffs after execution.
_MUTATING_TOOLS = {
    "write_file",
    "write_file_commit",  # final atomic step of a chunked write
    "append_file",        # also visible progress, even if pre-commit
    "edit_file",
    "apply_patch",
    "rename_symbol",
    "format_python",
    "delete_file",
    "move_file",
    "copy_file",
}


def _read_lines(path: str) -> list[str]:
    """
    Safely read a file and return its contents as a list of lines.

    Returns:
        [] if the file does not exist, is a directory,
        or cannot be read.
    """
    p = Path(path)

    if not p.exists() or p.is_dir():
        return []

    try:
        return p.read_text(
            encoding="utf-8",
            errors="ignore"
        ).splitlines()

    except Exception:
        return []


def _diff_counts(before: list[str], after: list[str]) -> tuple[int, int]:
    """
    Compute how many lines were added and removed between two versions
    of a file using a diff algorithm.

    Returns:
        (added_lines, removed_lines)
    """
    import difflib

    added = 0
    removed = 0

    # Compare line-by-line using SequenceMatcher.
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        a=before,
        b=after,
        autojunk=False
    ).get_opcodes():

        # Replaced lines count as both removed and added.
        if tag == "replace":
            removed += (i2 - i1)
            added += (j2 - j1)

        # Pure deletions.
        elif tag == "delete":
            removed += (i2 - i1)

        # Pure insertions.
        elif tag == "insert":
            added += (j2 - j1)

    return added, removed


def _patch_targets(patch_text: str) -> list[str]:
    """
    Extract target file paths from an apply_patch payload.

    Example matched lines:
        *** Update File: test.py
        *** Add File: new.py
        *** Delete File: old.py
    """
    targets: list[str] = []

    for m in re.finditer(
        r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+)$",
        patch_text,
        flags=re.MULTILINE,
    ):
        targets.append(m.group(1).strip())

    return targets


def _snapshot_before(name: str, args: dict) -> dict[str, list[str]]:
    """
    Capture the current contents of every file a tool may modify.

    Returns:
        {
            "path/to/file.py": ["line1", "line2", ...]
        }
    """
    paths: list[str] = []

    # apply_patch can affect multiple files.
    if name == "apply_patch":
        patch_text = args.get("patch", "")
        paths.extend(_patch_targets(patch_text))

    # move/copy affect both source and destination.
    elif name in {"move_file", "copy_file"}:
        src = args.get("src")
        dst = args.get("dst")

        if src:
            paths.append(src)

        if dst:
            paths.append(dst)

    # Most mutating tools only affect one path.
    else:
        p = args.get("path")

        if p:
            paths.append(p)

    # Read and store the file contents before modification.
    return {
        p: _read_lines(p)
        for p in paths
    }


def _update_toolbar(
    name: str,
    args: dict,
    before: dict[str, list[str]]
) -> None:
    """
    Compare file contents before/after execution and update the toolbar.

    The toolbar accumulates line additions/removals across multiple
    operations in the same turn.
    """
    for path, old_lines in before.items():
        new_lines = _read_lines(path)

        added, removed = _diff_counts(old_lines, new_lines)

        # Even if no diff exists, still show the touched file.
        if added == 0 and removed == 0:
            toolbar.update(
                file=path,
                delta_added=0,
                delta_removed=0
            )
            continue

        toolbar.update(
            file=path,
            delta_added=added,
            delta_removed=removed
        )


async def run_tool(tool: dict, timeout: float = 100):
    """
    Execute a single tool safely with timeout/error handling.

    Supports:
    - async tools
    - sync tools via asyncio.to_thread
    - flat tool JSON
    - nested {"args": {...}} format
    - optional base64-decoded content
    """
    name = tool.get("name")

    # Validate tool exists.
    if not name or name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {name}"}

    # Tool calls can arrive in two formats:
    #
    # Flat:
    #   {"name": "read_file", "path": "x.py"}
    #
    # Nested:
    #   {"name": "read_file", "args": {"path": "x.py"}}
    #
    # Always create a fresh dict so we don't mutate originals.
    if isinstance(tool.get("args"), dict):
        args = dict(tool["args"])

    else:
        args = {
            k: v
            for k, v in tool.items()
            if k != "name"
        }

    # Auto-decode base64 content if provided.
    if "content_b64" in args:
        args["content"] = decode_b64(args["content_b64"])

    fn = TOOL_REGISTRY[name]

    # Snapshot files before execution if the tool mutates state.
    before_snapshot: dict[str, list[str]] = {}

    if name in _MUTATING_TOOLS:
        before_snapshot = _snapshot_before(name, args)

    try:
        # Async tool.
        if asyncio.iscoroutinefunction(fn):
            result = await asyncio.wait_for(
                fn(args),
                timeout=timeout
            )

        # Sync tool.
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(fn, args),
                timeout=timeout
            )

    # Timeout handling.
    except asyncio.TimeoutError:
        return {"error": f"{name} timed out"}

    # Known tool errors.
    except ToolError as e:
        return {"error": str(e)}

    # Unknown/unexpected errors.
    except Exception as e:
        return {"error": str(e)}

    # Update toolbar with file diffs after execution.
    if before_snapshot:
        _update_toolbar(name, args, before_snapshot)

    return result


# Tools that must NEVER run concurrently.
#
# Running these in parallel can corrupt state:
# - append_file may race with write_file_commit
# - multiple writes may overwrite each other
# - patches may apply against stale content
#
# These tools are therefore serialized in emission order.
_SEQUENTIAL_TOOLS = {
    "write_file",
    "write_file_start",
    "append_file",
    "write_file_commit",
    "edit_file",
    "apply_patch",
    "rename_symbol",
    "format_python",
    "delete_file",
    "move_file",
    "copy_file",
    "mkdir",
    "run_command",
}


async def run_tools_parallel(tools: list, timeout=100):
    """
    Execute tools efficiently while preserving correctness.

    Strategy:
    - Read-only tools run concurrently for speed.
    - Mutating tools run sequentially in the exact order emitted.
    - Parallel batches are flushed before any sequential tool executes.
    """
    results: list = [None] * len(tools)

    # Accumulates read-only tools that can safely run together.
    parallel_batch: list[tuple[int, dict]] = []

    async def flush_parallel():
        """
        Execute the current parallel batch concurrently and store results.
        """
        if not parallel_batch:
            return

        idxs = [i for i, _ in parallel_batch]

        tasks = [
            run_tool(t, timeout)
            for _, t in parallel_batch
        ]

        outs = await asyncio.gather(*tasks)

        for i, out in zip(idxs, outs):
            results[i] = out

        parallel_batch.clear()

    # Walk tools in order.
    for i, tool in enumerate(tools):
        name = (tool or {}).get("name")

        # Sequential tool:
        # flush pending reads, then run alone.
        if name in _SEQUENTIAL_TOOLS:
            await flush_parallel()
            results[i] = await run_tool(tool, timeout)

        # Read-only tool:
        # queue for concurrent execution.
        else:
            parallel_batch.append((i, tool))

    # Run any remaining read-only tools.
    await flush_parallel()

    return results