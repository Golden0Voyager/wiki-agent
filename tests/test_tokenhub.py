import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_key = os.getenv("HUNYUAN_API_KEY")
    api_base = "https://tokenhub.tencentmaas.com/v1"
    model = "hy3-preview"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": "Return JSON: {\"test\": 1}"}
                ]
            },
            timeout=10.0
        )
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")

asyncio.run(main())
