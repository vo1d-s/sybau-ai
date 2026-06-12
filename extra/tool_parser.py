import json
import re

TOOL_OPEN = "<tool>"
TOOL_CLOSE = "</tool>"


def extract_tools(text: str):
    """Return successfully-parsed tool calls (back-compat shape)."""
    tools, _ = extract_tools_with_errors(text)
    return tools


def _scan_json_object(text: str, start: int) -> int:
    """Given text[start] == '{', return index just past the matching '}'.

    Tracks string state so braces or </tool> inside string values do not
    end the object early. Returns -1 if no balanced object is found.
    """
    if start >= len(text) or text[start] != "{":
        return -1

    depth = 0
    i = start
    in_string = False
    escape = False

    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1

    return -1


def _find_tool_blocks(text: str):
    """Yield (block_index, json_text, raw_start, raw_end) for each <tool>...</tool>.

    Uses JSON-aware scanning so a literal '</tool>' inside a string value
    does NOT prematurely close the block. After scanning the JSON object,
    verifies that the next non-whitespace tokens are '</tool>' before
    accepting the block; otherwise reports it as malformed.
    """
    idx = 0
    block_no = 0
    while True:
        open_at = text.find(TOOL_OPEN, idx)
        if open_at == -1:
            return
        block_no += 1
        json_start = open_at + len(TOOL_OPEN)

        # Skip leading whitespace before the '{'.
        j = json_start
        while j < len(text) and text[j].isspace():
            j += 1

        if j >= len(text) or text[j] != "{":
            # Not an object -- yield the raw span between open and the
            # nearest </tool> (best-effort) so the error reporter can
            # describe what was seen.
            close_at = text.find(TOOL_CLOSE, json_start)
            end = close_at if close_at != -1 else len(text)
            yield block_no, text[json_start:end], open_at, end
            idx = end + len(TOOL_CLOSE) if close_at != -1 else len(text)
            continue

        obj_end = _scan_json_object(text, j)
        if obj_end == -1:
            # Unterminated JSON. Report what we have and advance past the
            # block to avoid infinite loop.
            close_at = text.find(TOOL_CLOSE, json_start)
            end = close_at if close_at != -1 else len(text)
            yield block_no, text[json_start:end], open_at, end
            idx = end + len(TOOL_CLOSE) if close_at != -1 else len(text)
            continue

        # Verify the closing </tool> follows (allowing whitespace).
        k = obj_end
        while k < len(text) and text[k].isspace():
            k += 1

        if text.startswith(TOOL_CLOSE, k):
            yield block_no, text[j:obj_end], open_at, k + len(TOOL_CLOSE)
            idx = k + len(TOOL_CLOSE)
        else:
            # JSON parsed cleanly but no </tool> follows. Treat the block
            # as malformed and skip past the JSON object.
            yield block_no, text[j:obj_end], open_at, obj_end
            idx = obj_end


def extract_tools_with_errors(text: str):
    """Return (tools, errors).

    Uses JSON-aware scanning so a literal '</tool>' string inside a tool
    argument value does NOT prematurely close the block -- that bug caused
    the parser to mis-attribute paths between adjacent tool calls.
    """
    tools: list[dict] = []
    errors: list[str] = []

    for block_no, raw, _start, _end in _find_tool_blocks(text):
        stripped = raw.strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as e:
            preview = stripped[:140].replace("\n", " ")
            errors.append(
                f"tool #{block_no}: invalid JSON ({e.msg} at pos {e.pos}). "
                f"got: {preview!r}"
            )
            continue

        if not isinstance(parsed, dict):
            errors.append(
                f"tool #{block_no}: expected a JSON object, "
                f"got {type(parsed).__name__}"
            )
            continue

        if "name" not in parsed:
            errors.append(
                f"tool #{block_no}: missing required field 'name'"
            )
            continue

        tools.append(parsed)

    return tools, errors
