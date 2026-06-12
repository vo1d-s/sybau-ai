from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import register_tool, ToolError


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a unique suffix that cannot collide with write_file's atomic tmp
    # or the chunked-write buffer. Older code used ".tmp" for everything,
    # which races with concurrent or interleaved writers and can leave
    # orphan files behind.
    tmp = path.with_name(path.name + ".patch.tmp")
    tmp.write_text(content, encoding="utf-8", errors="ignore")
    tmp.replace(path)
    if not path.exists():
        raise ToolError(
            f"patch write failed: {path} does not exist after replace."
        )


def _parse_hunk(hunk_lines: list[str]) -> tuple[list[str], list[str]]:
    """
    Parse a simplified unified-diff hunk.

    Supported line prefixes:
      ' '  context
      '-'  removed from original
      '+'  added in new content

    Any line without a prefix is treated as context.
    """
    src: list[str] = []
    dst: list[str] = []

    for line in hunk_lines:
        if line == "":
            src.append("")
            dst.append("")
            continue

        prefix = line[:1]
        body = line[1:] if prefix in {" ", "-", "+"} else line

        if prefix == "-":
            src.append(body)
        elif prefix == "+":
            dst.append(body)
        else:
            src.append(body)
            dst.append(body)

    return src, dst


def _apply_hunks(original: str, hunks: list[list[str]]) -> str:
    original_had_trailing_newline = original.endswith("\n")
    lines = original.splitlines()

    search_from = 0

    for hunk in hunks:
        src, dst = _parse_hunk(hunk)

        if not src and not dst:
            continue

        if not src:
            raise ToolError(
                "Patch hunk has only insertions. Include at least one context line "
                "or one removed line so the patch can be anchored."
            )

        found_at = None
        for i in range(search_from, len(lines) - len(src) + 1):
            if lines[i : i + len(src)] == src:
                found_at = i
                break

        if found_at is None:
            raise ToolError(
                "Could not locate patch hunk in file. "
                "Add more context lines around the change."
            )

        lines = lines[:found_at] + dst + lines[found_at + len(src) :]
        search_from = found_at + len(dst)

    result = "\n".join(lines)
    if original_had_trailing_newline:
        result += "\n"
    return result


def _parse_patch_text(patch_text: str) -> list[dict[str, Any]]:
    """
    Patch format:

    *** Begin Patch
    *** Update File: path/to/file
    @@
     context
    -old
    +new
     context
    @@
    ...
    *** Add File: path/to/new_file
    +first line
    +second line
    *** Delete File: path/to/old_file
    *** End Patch
    """
    lines = patch_text.splitlines()
    i = 0
    ops: list[dict[str, Any]] = []

    while i < len(lines):
        line = lines[i].strip()

        if not line or line == "*** Begin Patch":
            i += 1
            continue

        if line == "*** End Patch":
            break

        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: ") :].strip()
            i += 1

            hunks: list[list[str]] = []
            current_hunk: list[str] | None = None

            while i < len(lines):
                raw = lines[i].rstrip("\n")
                stripped = raw.strip()

                if stripped.startswith("*** "):
                    break

                if stripped.startswith("@@"):
                    if current_hunk is not None:
                        hunks.append(current_hunk)
                    current_hunk = []
                    i += 1
                    continue

                if current_hunk is None:
                    i += 1
                    continue

                current_hunk.append(raw)
                i += 1

            if current_hunk is not None:
                hunks.append(current_hunk)

            ops.append({"op": "update", "path": path, "hunks": hunks})
            continue

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: ") :].strip()
            i += 1

            content_lines: list[str] = []
            while i < len(lines):
                raw = lines[i].rstrip("\n")
                if raw.strip().startswith("*** "):
                    break

                if raw.startswith("+"):
                    content_lines.append(raw[1:])
                else:
                    content_lines.append(raw)

                i += 1

            ops.append({"op": "add", "path": path, "content": "\n".join(content_lines)})
            continue

        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: ") :].strip()
            ops.append({"op": "delete", "path": path})
            i += 1
            continue

        i += 1

    return ops


@register_tool("apply_patch", "Apply a structured patch to one or more files")
def apply_patch(args: dict) -> str:
    patch_text = args.get("patch")

    if not patch_text:
        raise ToolError("Missing patch")

    ops = _parse_patch_text(patch_text)

    if not ops:
        raise ToolError("No patch operations found")

    # Two-phase: validate + compute new content for every op first, then
    # commit to disk. If any op fails, nothing is written.
    planned_writes: list[tuple[Path, str, str]] = []   # (path, content, verb)
    planned_deletes: list[tuple[Path, str]] = []       # (path, verb)

    for op in ops:
        path = Path(op["path"])

        if op["op"] == "add":
            if path.exists():
                raise ToolError(f"File already exists: {path}")
            # Also reject if an earlier planned write targets the same path.
            if any(p == path for p, _, _ in planned_writes):
                raise ToolError(f"Duplicate add for: {path}")
            planned_writes.append((path, op["content"], "added"))

        elif op["op"] == "delete":
            if not path.exists():
                raise ToolError(f"File not found: {path}")
            if path.is_dir():
                raise ToolError(f"Refusing to delete directory: {path}")
            planned_deletes.append((path, "deleted"))

        elif op["op"] == "update":
            if not path.exists():
                raise ToolError(f"File not found: {path}")
            if path.is_dir():
                raise ToolError(f"Not a file: {path}")

            # If a prior op in this patch already updated this path, chain
            # from that in-memory result rather than the on-disk version.
            prior = next(
                (content for p, content, _ in reversed(planned_writes) if p == path),
                None,
            )
            original = (
                prior if prior is not None
                else path.read_text(encoding="utf-8", errors="ignore")
            )
            updated = _apply_hunks(original, op["hunks"])
            planned_writes.append((path, updated, "updated"))

        else:
            raise ToolError(f"Unknown patch op: {op['op']}")

    # Commit phase. We've validated everything; failures here are I/O errors
    # that we can't roll back, but the common bug class (a bad hunk in op 3
    # leaving ops 1-2 committed) is now impossible.
    results: list[str] = []
    for path, content, verb in planned_writes:
        _write_atomic(path, content)
        results.append(f"{verb} {path}")
    for path, verb in planned_deletes:
        path.unlink()
        results.append(f"{verb} {path}")

    return "\n".join(results)