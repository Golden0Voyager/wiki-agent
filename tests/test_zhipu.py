import asyncio
import logging

import pytest

from wiki_service import WikiService

logging.basicConfig(level=logging.INFO)


@pytest.mark.skip(reason="Integration test requiring API keys")
async def test():
    ws = WikiService()
    res = await ws._call_llm_text("Say hi", "hi", max_retries=3)
    assert res is not None


if __name__ == "__main__":
    asyncio.run(test())
