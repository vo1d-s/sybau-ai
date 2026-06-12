import urllib.request
from .registry import register_tool, ToolError


@register_tool("http_get", "Fetch a URL (text only)")
def http_get(args: dict) -> str:
    url = args.get("url")

    if not url:
        raise ToolError("Missing url")

    try:
        with urllib.request.urlopen(url) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        raise ToolError(str(e))