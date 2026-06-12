import subprocess
import platform
import os
import shutil
import sys
from .registry import register_tool, ToolError


# ----------------------------
# RUN COMMAND (SAFE-ish)
# ----------------------------
@register_tool("run_command", "Run shell command. Args: cmd (or command). 'wait' (bool, default True): if True, wait for completion and return output; if False, launch in background and return immediately.")
def run_command(args: dict) -> str:
    # Accept either 'cmd' or 'command' -- the system prompt advertises 'cmd'
    # but older callers used 'command'. Rejecting one silently broke every
    # shell call from the agent.
    cmd = args.get("cmd") or args.get("command")

    if not cmd:
        raise ToolError("Missing cmd")

    wait = args.get("wait", True)
    if isinstance(wait, str):
        wait = wait.strip().lower() not in ("false", "0", "no", "off")

    if not wait:
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return f"Command launched in background (pid={proc.pid})"
        except Exception as e:
            raise ToolError(f"Failed to launch command: {e}")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr
    except Exception as e:
        raise ToolError(str(e))


# ----------------------------
# RUN COMMAND STREAM (line by line)
# ----------------------------
@register_tool("run_command_stream", "Run shell command and stream output line-by-line into a single string. Args: cmd (or command), max_lines (optional cap)")
def run_command_stream(args: dict) -> str:
    cmd = args.get("cmd") or args.get("command")
    max_lines = args.get("max_lines")

    if not cmd:
        raise ToolError("Missing cmd")

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        raise ToolError(str(e))

    collected = []
    cap = int(max_lines) if max_lines is not None else None

    assert proc.stdout is not None
    for line in proc.stdout:
        collected.append(line.rstrip("\n"))
        if cap is not None and len(collected) >= cap:
            break

    proc.wait()
    return "\n".join(collected) + f"\n[exit code: {proc.returncode}]"


# ----------------------------
# OPEN CMD
# ----------------------------
@register_tool("open_cmd", "Open system terminal")
def open_cmd(args: dict) -> str:
    if platform.system() == "Windows":
        os.system("start cmd")
    else:
        os.system("x-terminal-emulator")

    return "Terminal opened"


# ----------------------------
# OPEN BROWSER
# ----------------------------
@register_tool("open_browser", "Open URL in default browser. Args: url")
def open_browser(args: dict) -> str:
    url = args.get("url")
    if not url:
        raise ToolError("Missing url")

    import webbrowser
    webbrowser.open(url)
    return f"Opened {url}"


# ----------------------------
# CURRENT DIRECTORY
# ----------------------------
@register_tool("pwd", "Get current working directory")
def pwd(args: dict) -> str:
    return os.getcwd()


# ----------------------------
# ENV VAR GET
# ----------------------------
@register_tool("get_env", "Get environment variable")
def get_env(args: dict) -> str:
    key = args.get("key")

    if not key:
        raise ToolError("Missing key")

    return os.getenv(key, "")


# ----------------------------
# ENV VAR SET (process scope)
# ----------------------------
@register_tool("set_env", "Set environment variable for current process. Args: key, value")
def set_env(args: dict) -> str:
    key = args.get("key")
    value = args.get("value", "")

    if not key:
        raise ToolError("Missing key")

    os.environ[key] = str(value)
    return f"set {key}={value}"


# ----------------------------
# WHICH (locate executable)
# ----------------------------
@register_tool("which", "Locate an executable on PATH. Args: name")
def which_tool(args: dict) -> str:
    name = args.get("name")
    if not name:
        raise ToolError("Missing name")

    found = shutil.which(name)
    return found if found else f"{name}: not found"


# ----------------------------
# SYSTEM INFO
# ----------------------------
@register_tool("system_info", "Get OS and runtime info")
def system_info(args: dict) -> str:
    info = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "python_exe": sys.executable,
        "cwd": os.getcwd(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME", ""),
        "cpu_count": os.cpu_count(),
    }
    return "\n".join(f"{k}: {v}" for k, v in info.items())


# ----------------------------
# PROCESS STATUS
# ----------------------------
@register_tool("process_status", "Check whether a process (pid) is running. Args: pid")
def process_status(args: dict) -> str:
    pid = args.get("pid")
    if pid is None:
        raise ToolError("Missing pid")

    try:
        pid = int(pid)
    except Exception:
        raise ToolError("Invalid pid")

    if platform.system() == "Windows":
        result = subprocess.run(
            f'tasklist /FI "PID eq {pid}"',
            shell=True, capture_output=True, text=True,
        )
        out = result.stdout
        if str(pid) in out:
            return f"pid {pid}: running\n{out}"
        return f"pid {pid}: not running"
    else:
        try:
            os.kill(pid, 0)
            return f"pid {pid}: running"
        except ProcessLookupError:
            return f"pid {pid}: not running"
        except PermissionError:
            return f"pid {pid}: running (no permission to signal)"


# ----------------------------
# PROCESS KILL
# ----------------------------
@register_tool("process_kill", "Kill a process by pid. Args: pid, force (bool)")
def process_kill(args: dict) -> str:
    pid = args.get("pid")
    force = bool(args.get("force", False))

    if pid is None:
        raise ToolError("Missing pid")

    try:
        pid = int(pid)
    except Exception:
        raise ToolError("Invalid pid")

    if platform.system() == "Windows":
        flag = "/F" if force else ""
        result = subprocess.run(
            f"taskkill {flag} /PID {pid}",
            shell=True, capture_output=True, text=True,
        )
        return (result.stdout + result.stderr).strip() or f"sent kill to {pid}"
    else:
        import signal
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            return f"killed pid {pid}"
        except ProcessLookupError:
            return f"pid {pid}: not running"
        except PermissionError:
            raise ToolError("Permission denied")
