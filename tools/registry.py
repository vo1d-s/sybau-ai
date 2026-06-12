from typing import Callable, Dict, Any

TOOL_REGISTRY: Dict[str, Callable] = {}
TOOL_DESCRIPTIONS: Dict[str, str] = {}

class ToolError(Exception):
    pass


def register_tool(name: str, description: str):
    def decorator(fn):
        TOOL_REGISTRY[name] = fn
        TOOL_DESCRIPTIONS[name] = description
        return fn
    return decorator