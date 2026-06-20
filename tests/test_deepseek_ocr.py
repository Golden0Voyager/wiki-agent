import asyncio
import os

import httpx


async def main():
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        print("No SILICONFLOW_API_KEY")
        return

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.siliconflow.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-ai/DeepSeek-OCR",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
                ]
            },
            timeout=10.0
        )
        print(resp.status_code)
        print(resp.text)

asyncio.run(main())
