import shutil
import os
import fnmatch
import time
from pathlib import Path
from tools.registry import register_tool, ToolError


@register_tool("write_file", "Write file safely. For files >100 lines, prefer write_file_start + append_file + write_file_commit to avoid stream-truncation bugs.")
def write_file(args: dict) -> str:
    path = args.get("path")
    content = args.get("content", "")

    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Use a unique tmp suffix that cannot collide with chunked-write
    # buffers. Older code used ".tmp" for both, which caused races.
    tmp = p.with_suffix(p.suffix + ".atomic.tmp")

    tmp.write_text(content, encoding="utf-8", errors="ignore")
    tmp.replace(p)

    # Sanity check -- never report success if the file isn't there.
    if not p.exists():
        raise ToolError(
            f"write failed: {path} does not exist after replace. "
            f"Check filesystem permissions or antivirus interference."
        )

    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return f"wrote {path} ({lines} lines, {p.stat().st_size} bytes)"


# Chunked writes use a dedicated suffix that CANNOT collide with the
# atomic .tmp used by write_file. This prevents the bug where a stray
# write_file call clobbers an in-progress chunked write (or vice-versa)
# and leaves orphan .tmp files behind.
_CHUNK_SUFFIX = ".chunkwrite"


def _chunk_path(p: Path) -> Path:
    return p.with_suffix(p.suffix + _CHUNK_SUFFIX)


@register_tool(
    "write_file_start",
    "Begin a chunked write. Args: path. Truncates any prior in-progress "
    "chunked write for this path. Follow with append_file calls, then "
    "write_file_commit.",
)
def write_file_start(args: dict) -> str:
    path = args.get("path")
    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    chunk = _chunk_path(p)
    chunk.write_text("", encoding="utf-8")
    return f"started chunked write to {path} (chunk buffer: {chunk.name})"


@register_tool(
    "append_file",
    "Append a chunk to an in-progress chunked write. Args: path, content. "
    "Keep each chunk small (~30 lines) so no single tool call can be "
    "truncated mid-stream.",
)
def append_file(args: dict) -> str:
    path = args.get("path")
    content = args.get("content", "")
    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    chunk = _chunk_path(p)
    if not chunk.exists():
        raise ToolError(
            f"No chunked write in progress for {path}. "
            f"Call write_file_start first."
        )

    with chunk.open("a", encoding="utf-8") as f:
        f.write(content)
    size = chunk.stat().st_size
    return f"appended {len(content)} chars to {path} (buffer now {size} bytes)"


@register_tool(
    "write_file_commit",
    "Finalize a chunked write -- atomically replaces the target. Args: path. "
    "After this returns, the target file is guaranteed to exist with the "
    "committed contents.",
)
def write_file_commit(args: dict) -> str:
    path = args.get("path")
    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    chunk = _chunk_path(p)
    if not chunk.exists():
        raise ToolError(
            f"No chunked write in progress for {path}. "
            f"Call write_file_start first."
        )

    # Atomic replace: move the chunk buffer over the target. On both POSIX
    # and Windows (Py 3.3+) Path.replace is atomic when src and dst are on
    # the same filesystem, which they always are here.
    chunk.replace(p)

    # Sanity check: target MUST exist now. If it doesn't, something is
    # very wrong (permissions, AV interference, etc.) and we must NOT
    # report success -- that's how the user ended up with a phantom save.
    if not p.exists():
        raise ToolError(
            f"commit failed: {path} does not exist after replace. "
            f"Check filesystem permissions or antivirus interference."
        )

    try:
        lines = sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
        size = p.stat().st_size
    except Exception:
        lines = -1
        size = -1
    return f"committed {path} ({lines} lines, {size} bytes)"


@register_tool("read_file", "Read file with line numbers")
def read_file(args: dict) -> str:
    path = args.get("path")

    if not path:
        raise ToolError("Missing path")

    p = Path(path)

    if not p.exists():
        raise ToolError("File not found")
    if p.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")

    return "\n".join(
        f"{i+1}: {l}"
        for i, l in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines())
    )


@register_tool("read_file_range", "Read specific line range from file. Args: path, start (1-based), end (inclusive)")
def read_file_range(args: dict) -> str:
    path = args.get("path")
    start = int(args.get("start", 1))
    end = args.get("end")

    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    if not p.exists():
        raise ToolError("File not found")
    if p.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")

    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    end = int(end) if end is not None else len(lines)

    start = max(1, start)
    end = min(len(lines), end)

    return "\n".join(
        f"{i}: {lines[i-1]}" for i in range(start, end + 1)
    )


@register_tool(
    "edit_file",
    "Replace exact text in a file. Args: path, old_text, new_text. "
    "Fails if old_text is not found, or if it appears more than once "
    "(include more surrounding context to disambiguate).",
)
def edit_file(args: dict) -> str:
    path = args.get("path")
    old_text = args.get("old_text")
    new_text = args.get("new_text")

    if not path:
        raise ToolError("Missing path")
    if old_text is None:
        raise ToolError("Missing old_text")
    if new_text is None:
        raise ToolError("Missing new_text")

    p = Path(path)
    if not p.exists():
        raise ToolError("File not found")
    if p.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")

    content = p.read_text(encoding="utf-8", errors="ignore")

    count = content.count(old_text)
    if count == 0:
        raise ToolError(
            f"old_text not found in {path}. Check whitespace/indentation."
        )
    if count > 1:
        raise ToolError(
            f"old_text appears {count} times in {path}; include more "
            f"surrounding context so exactly one occurrence matches."
        )

    updated = content.replace(old_text, new_text, 1)

    tmp = p.with_suffix(p.suffix + ".atomic.tmp")
    tmp.write_text(updated, encoding="utf-8", errors="ignore")
    tmp.replace(p)

    if not p.exists():
        raise ToolError(
            f"edit failed: {path} does not exist after replace."
        )

    return f"Edited {path} \u2014 replaced 1 occurrence"


@register_tool("mkdir", "Create directory")
def mkdir(args: dict) -> str:
    path = args.get("path")

    if not path:
        raise ToolError("Missing path")

    Path(path).mkdir(parents=True, exist_ok=True)

    return f"created {path}"


@register_tool("list_dir", "List directory contents. Args: path (default '.'), recursive (bool)")
def list_dir(args: dict) -> str:
    path = args.get("path", ".")
    recursive = bool(args.get("recursive", False))

    p = Path(path)
    if not p.exists():
        raise ToolError("Path not found")
    if not p.is_dir():
        raise ToolError("Not a directory")

    entries = []
    if recursive:
        for sub in p.rglob("*"):
            kind = "D" if sub.is_dir() else "F"
            entries.append(f"{kind} {sub.as_posix()}")
    else:
        for sub in sorted(p.iterdir()):
            kind = "D" if sub.is_dir() else "F"
            entries.append(f"{kind} {sub.name}")

    return "\n".join(entries) if entries else "(empty)"


@register_tool("search_files", "Search filenames by glob pattern. Args: path (default '.'), pattern (e.g. '*.py')")
def search_files(args: dict) -> str:
    root = args.get("path", ".")
    pattern = args.get("pattern")

    if not pattern:
        raise ToolError("Missing pattern")

    matches = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if fnmatch.fnmatch(name, pattern):
                matches.append(os.path.join(dirpath, name))

    return "\n".join(matches) if matches else "No matches"


@register_tool("delete_file", "Delete a file or directory. Args: path, recursive (bool, for dirs)")
def delete_file(args: dict) -> str:
    path = args.get("path")
    recursive = bool(args.get("recursive", False))

    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    if not p.exists():
        raise ToolError("Path not found")

    if p.is_dir():
        if recursive:
            shutil.rmtree(p)
        else:
            try:
                p.rmdir()
            except OSError as e:
                raise ToolError(
                    f"Cannot delete non-empty directory {path!s}. "
                    f"Pass recursive=true to remove its contents. ({e})"
                )
        return f"deleted dir {path}"
    else:
        p.unlink()
        return f"deleted {path}"


@register_tool("copy_file", "Copy file or directory. Args: src, dst")
def copy_file(args: dict) -> str:
    src = args.get("src")
    dst = args.get("dst")

    if not src or not dst:
        raise ToolError("Missing src/dst")

    sp = Path(src)
    if not sp.exists():
        raise ToolError("Source not found")

    if sp.is_dir():
        shutil.copytree(sp, dst)
    else:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, dst)

    return f"copied {src} -> {dst}"


@register_tool("move_file", "Move/rename file or directory. Args: src, dst")
def move_file(args: dict) -> str:
    src = args.get("src")
    dst = args.get("dst")

    if not src or not dst:
        raise ToolError("Missing src/dst")

    if not Path(src).exists():
        raise ToolError("Source not found")

    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dst)

    return f"moved {src} -> {dst}"


@register_tool("file_info", "Get file metadata (size, mtime, type). Args: path")
def file_info(args: dict) -> str:
    path = args.get("path")
    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    if not p.exists():
        raise ToolError("Path not found")

    st = p.stat()
    kind = "dir" if p.is_dir() else "file"
    return (
        f"path: {p.as_posix()}\n"
        f"type: {kind}\n"
        f"size: {st.st_size}\n"
        f"mtime: {time.ctime(st.st_mtime)}\n"
        f"ctime: {time.ctime(st.st_ctime)}\n"
        f"abs: {p.resolve().as_posix()}"
    )


@register_tool("tail_file", "Read last N lines of a file. Args: path, lines (default 20)")
def tail_file(args: dict) -> str:
    path = args.get("path")
    n = int(args.get("lines", 20))

    if not path:
        raise ToolError("Missing path")

    p = Path(path)
    if not p.exists():
        raise ToolError("File not found")
    if p.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")

    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    tail = lines[-n:]
    start = len(lines) - len(tail) + 1
    return "\n".join(f"{start+i}: {l}" for i, l in enumerate(tail))


@register_tool(
    "edit_file",
    "Replace exact text in a file. Args: path, old_text, new_text. "
    "Fails if old_text is not found, or if it appears more than once "
    "(to prevent ambiguous edits -- include more context to disambiguate).",
)
def edit_file(args: dict) -> str:
    path = args.get("path")
    old_text = args.get("old_text")
    new_text = args.get("new_text")

    if not path:
        raise ToolError("Missing path")
    if old_text is None:
        raise ToolError("Missing old_text")
    if new_text is None:
        raise ToolError("Missing new_text")

    p = Path(path)
    if not p.exists():
        raise ToolError("File not found")
    if p.is_dir():
        raise ToolError(f"Path is a directory, not a file: {path}")

    content = p.read_text(encoding="utf-8", errors="ignore")

    count = content.count(old_text)
    if count == 0:
        raise ToolError(
            f"old_text not found in {path}. Check whitespace and exact match."
        )
    if count > 1:
        raise ToolError(
            f"old_text appears {count} times in {path}. Include more "
            f"surrounding context so exactly one occurrence matches."
        )

    updated = content.replace(old_text, new_text, 1)

    tmp = p.with_suffix(p.suffix + ".atomic.tmp")
    tmp.write_text(updated, encoding="utf-8", errors="ignore")
    tmp.replace(p)

    if not p.exists():
        raise ToolError(
            f"edit failed: {path} does not exist after replace."
        )

    return f"Edited {path} \u2014 replaced 1 occurrence"
