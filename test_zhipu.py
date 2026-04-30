import asyncio
from wiki_service import WikiService
import logging

logging.basicConfig(level=logging.INFO)

async def test():
    ws = WikiService()
    print("Keys available:", len(ws.api_keys))
    res = await ws._call_llm_text("Say hi", "hi", max_retries=3)
    print("Response:", res)

asyncio.run(test())
