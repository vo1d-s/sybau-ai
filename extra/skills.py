from pathlib import Path
import re

from extra.storage import load_config, save_config

# Key under which the active skills folder path is persisted.
_CONFIG_KEY = "skills_dir"

# Default location: a top-level ./skills directory next to the project root.
_DEFAULT_DIR = "skills"


def get_skills_dir() -> Path:
    """Return the currently configured skills directory as a Path.

    Falls back to the default ./skills if nothing is configured.
    """
    cfg = load_config()
    raw = cfg.get(_CONFIG_KEY) or _DEFAULT_DIR
    return Path(raw).expanduser()


def set_skills_dir(path: str) -> Path:
    """Persist a new skills directory and return it as a Path."""
    cfg = load_config()
    p = Path(path).expanduser()
    cfg[_CONFIG_KEY] = str(p)
    save_config(cfg)
    return p


def _parse_skill_md(text: str) -> dict:
    """Extract metadata from a SKILL.md file.

    Supports an optional YAML-style frontmatter block delimited by '---'.
    Recognizes 'name' and 'description' keys. Falls back to the first
    heading / first non-empty line when frontmatter is absent.
    """
    name = None
    description = None

    fm_match = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if fm_match:
        block = fm_match.group(1)
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip().strip('"').strip("'")
            if key == "name" and val:
                name = val
            elif key == "description" and val:
                description = val

    if not name:
        heading = re.search(r"^\s*#\s+(.+)$", text, re.MULTILINE)
        if heading:
            name = heading.group(1).strip()

    if not description:
        # First non-empty, non-heading, non-frontmatter line.
        body = text
        if fm_match:
            body = text[fm_match.end():]
        for line in body.splitlines():
            s = line.strip()
            if s and not s.startswith("#") and s != "---":
                description = s
                break

    return {"name": name, "description": description}


def _skill_md_path(skill_dir: Path) -> Path | None:
    """Return the SKILL.md path inside a skill dir, case-insensitively."""
    if not skill_dir.is_dir():
        return None
    for child in skill_dir.iterdir():
        if child.is_file() and child.name.lower() == "skill.md":
            return child
    return None


def list_skills() -> list[dict]:
    """Scan the configured skills dir and return skill metadata.

    Each entry: {id, name, description, dir, md_path}. The folder name is
    used as a stable identifier; the parsed 'name' is used for display
    when present, otherwise the folder name.
    """
    base = get_skills_dir()
    skills: list[dict] = []
    if not base.is_dir():
        return skills

    for entry in sorted(base.iterdir()):
        md_path = _skill_md_path(entry)
        if md_path is None:
            continue
        meta = _parse_skill_md(md_path.read_text(encoding="utf-8", errors="replace"))
        skills.append({
            "id": entry.name,
            "name": meta.get("name") or entry.name,
            "description": meta.get("description") or "",
            "dir": str(entry),
            "md_path": str(md_path),
        })
    return skills


def read_skill(identifier: str) -> str | None:
    """Return the full SKILL.md text for a skill by folder name or parsed name.

    Matching is case-insensitive and checks the folder id first, then the
    parsed display name. Returns None if no skill matches.
    """
    target = identifier.strip().lower()
    for skill in list_skills():
        if skill["id"].lower() == target or skill["name"].lower() == target:
            return Path(skill["md_path"]).read_text(encoding="utf-8", errors="replace")
    return None


def skills_prompt_block() -> str:
    """Build the text injected into the system prompt listing skills.

    Returns an empty string when no skills are available so the prompt
    stays clean.
    """
    skills = list_skills()
    if not skills:
        return ""

    lines = ["These are the skills you have available:"]
    for skill in skills:
        desc = skill["description"] or "(no description)"
        lines.append(f"- {skill['name']}: {desc}")
    lines.append("")
    lines.append("To read them, use <read_skill>name</read_skill>")
    lines.append("You can read multiple skills at the same time.")
    return "\n".join(lines)
