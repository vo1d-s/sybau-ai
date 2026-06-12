from rich.console import Console
from extra.models import MODELS

console = Console()

def print_title():
    console.print("[bold orange1] -- SYBAU AI -- [/bold orange1]")

def print_model_name(selected):
    model = next(m for m in MODELS if m["id"] == selected)
    console.print(f"[bold orange1]{model['name']}[/bold orange1]")

def print_tools(names):
    console.print(f"[bright_black]Running tools: [italic]{names}[/italic][/bright_black]")

def print_models_load(selected):
    model = next(m for m in MODELS if m["id"] == selected)
    console.print(f"[bright_black]Loaded [bright_cyan]{len(MODELS)} models[/bright_cyan].\nSelected: [bright_cyan]{model['name']}[/bright_cyan] ({model['id']})[bright_black]\n")