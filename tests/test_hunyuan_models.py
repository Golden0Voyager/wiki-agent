import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_key = os.getenv("HUNYUAN_API_KEY")
    api_base = os.getenv("HUNYUAN_BASE_URL", "https://api.hunyuan.cloud.tencent.com/v1")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_base}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")

asyncio.run(main())
