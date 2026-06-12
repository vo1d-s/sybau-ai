import requests
from config.settings import API_BASE

# get models from api for selecting model commands
r_models = requests.get(f"{API_BASE}/api/models")
MODELS = r_models.json()["data"]