from rich.console import Console
from extra.models import MODELS

console = Console()


def arrow_select(title, options):
    """Show an arrow-key navigable menu and return the selected index.

    `options` is a list of (label, description) tuples or plain strings.
    Returns the chosen index, or None if cancelled (Esc / Ctrl-C / q).
    Falls back to numbered input when readchar is unavailable.
    """
    items = [o if isinstance(o, tuple) else (o, "") for o in options]

    try:
        import readchar
    except ImportError:
        return _numbered_select(title, items)

    idx = 0

    def render():
        console.print(f"\n[bold orange1]{title}[/bold orange1]")
        for i, (label, desc) in enumerate(items):
            pointer = "[bold bright_cyan]>[/bold bright_cyan]" if i == idx else " "
            style = "bold bright_white" if i == idx else "bright_black"
            line = f" {pointer} [{style}]{label}[/{style}]"
            if desc:
                line += f" [bright_black]- {desc}[/bright_black]"
            console.print(line)

    render()
    while True:
        key = readchar.readkey()
        if key in (readchar.key.UP, "k"):
            idx = (idx - 1) % len(items)
        elif key in (readchar.key.DOWN, "j"):
            idx = (idx + 1) % len(items)
        elif key in ("\r", "\n", readchar.key.ENTER):
            return idx
        elif key in (readchar.key.ESC, "q", "\x03"):
            return None
        else:
            continue
        # redraw in place: move cursor up over the rendered block
        console.file.write(f"\x1b[{len(items) + 1}A")
        render()


def _numbered_select(title, items):
    """Fallback selector using numbered input (no readchar)."""
    console.print(f"\n[bold orange1]{title}[/bold orange1]")
    for i, (label, desc) in enumerate(items):
        line = f"  [bright_cyan]{i + 1}[/bright_cyan]. {label}"
        if desc:
            line += f" [bright_black]- {desc}[/bright_black]"
        console.print(line)
    raw = console.input("[bright_black]Select a number (blank to cancel): [/bright_black]").strip()
    if not raw.isdigit():
        return None
    n = int(raw) - 1
    return n if 0 <= n < len(items) else None


def pick_folder():
    """Open the native OS folder picker and return the chosen path, or None.

    Falls back to a typed-path prompt when a GUI is unavailable.
    """
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select skills folder")
        root.destroy()
        return path or None
    except Exception:
        raw = console.input(
            "[bright_black]Enter skills folder path (blank to cancel): [/bright_black]"
        ).strip()
        return raw or None


def print_skills(skills):
    """Print the list of discovered skills."""
    if not skills:
        console.print("[bright_black]No skills found in the current folder.[/bright_black]")
        return
    console.print("[bold orange1]Available skills:[/bold orange1]")
    for s in skills:
        desc = s.get("description") or "(no description)"
        console.print(
            f"  [bold bright_white]{s['name']}[/bold bright_white] "
            f"[bright_black]- {desc}[/bright_black]"
        )

def print_title():
    console.print("[bold orange1] -- SYBAU AI -- [/bold orange1]")

def print_model_name(selected):
    model = next(m for m in MODELS if m["id"] == selected)
    console.print(f"[bold orange1]{model['name']}[/bold orange1]")

def print_tools(names):
    console.print(f"[bright_black]Running tools: [italic]{names}[/italic][/bright_black]")

def truncate(text, limit=10):
    first = text.splitlines()[0]
    return first[:limit] + ("..." if len(first) > limit or "\n" in text else "")

def print_tool_results(tools, results):
    for i, tool in enumerate(tools):
        result = str(results[i])

        formatted_args = ", ".join(
            f"{n}='{truncate(str(v))}'"
            for n, v in tool.items()
            if n != "name"
        )

        lines = result.splitlines()

        if lines:
            preview = f"  {truncate(lines[0], 80)}\n"

            if len(lines) > 1:
                preview += f"  ...  {len(lines) - 1} more lines\n"
        else:
            preview = "  <empty>\n"

        console.print(
            f"[bold bright_white]{tool.get('name', '?')}[/bold bright_white]  "
            f"[bright_black]{formatted_args}[/bright_black]"
        )

        console.print(f"[bright_black]{preview}[/bright_black]")

def print_models_load(selected):
    model = next(m for m in MODELS if m["id"] == selected)
    console.print(f"[bright_black]Loaded [bright_cyan]{len(MODELS)} models[/bright_cyan].\nSelected: [bright_cyan]{model['name']}[/bright_cyan] ({model['id']})[bright_black]\n")