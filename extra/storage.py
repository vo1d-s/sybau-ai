from pathlib import Path
import json

# default dirs where data will be saved
USERDIR = Path.home() / ".sybauai"
CONFIG_FILE = USERDIR / "config.json" # jSON im crine

# create data dir if it doesnt exist
def ensure_dir():
    USERDIR.mkdir(exist_ok=True)

def save_config(data):
    ensure_dir()
     # write config as json
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False,indent=2), encoding="utf-8")

def load_config():
    # return data as json if file exists and can be parsed
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    return {}