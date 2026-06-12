import httpx
import json
import uuid
from typing import AsyncIterator
from config.settings import API_BASE, API_TIMEOUT

# api key handler, generates if not one already saved or if new requested
API_KEY = None
async def _api_key(new: bool = False) -> str:
    global API_KEY

    # doesnt exist or new requested...
    if not API_KEY or (API_KEY and new):
        # call api for key
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            res = await client.get(
                url=f"{API_BASE}/api/key"
            )
            res.raise_for_status()

            API_KEY = res.json()["key"]
    
    return API_KEY

# memory token handler, generates if not one already saved or if new requested
MEMORY_TOKEN = None
def _memory_token(new: bool = False) -> str:
    global MEMORY_TOKEN

    # doesnt exist or new requested...
    if not MEMORY_TOKEN or (MEMORY_TOKEN and new):
        MEMORY_TOKEN = f"{uuid.uuid4()}_{uuid.uuid4()}"

    return MEMORY_TOKEN

# chat stream api handler
async def stream_chat(user_message: str, model_id: str, system_prompt: str, memory: list) -> AsyncIterator[dict]:
    api_key = await _api_key() # get saved api key
    memory_token = _memory_token() # get saved memory token
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    body = {
        "message": user_message,
        "model": model_id,
        "customInstructions": system_prompt,
        "effort": "high",
        "conversation": memory,
        "remember": True,
        "memoryToken": memory_token,
    }
    
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        # call chat stream api
        async with client.stream(
            method="POST",
            url=f"{API_BASE}/api/chat",
            headers=headers,
            json=body
        ) as res:
            res.raise_for_status()

            # for line in response
            async for line in res.aiter_lines():
                # check if actual data
                if not line.startswith("data: "):
                    continue
                
                # remove unnecessary stuff
                raw = line[6:].strip()
                if not raw:
                    continue
                
                # try parse chunk as json
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError: # error = line is not complete, continue
                    continue