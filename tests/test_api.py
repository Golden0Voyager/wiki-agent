
import httpx
import pytest


@pytest.mark.skipif(True, reason="Requires running API server at localhost:8000")
def test_wiki_ingest_endpoint():
    print("🚀 Starting WikiAgent Integration Test via API...")

    # 模拟数据 1: x_digest 科技推文
    print("\n[Test 1] Simulating x_digest ingestion...")
    payload_x = {
        "source_project": "x_digest",
        "topic": "NV_Earnings_Report",
        "content": "今日 #英伟达 发布财报，提到 #液冷技术 在 AI 算力中心的大规模应用，这将利好 A 股的液冷板块。",
        "metadata": {"author": "TechWire"}
    }

    try:
        response = httpx.post("http://127.0.0.1:8000/api/v1/wiki/ingest", json=payload_x)
        print(f"✅ Response Status: {response.status_code}")
        print(f"📄 JSON Data: {response.json()}")
    except Exception as e:
        print(f"❌ Failed to connect to API: {e}. Please ensure `uvicorn api:app --reload` is running.")
        return

    # 模拟数据 2: quant_lab 个股深度分析
    print("\n[Test 2] Simulating quant_lab ingestion...")
    payload_q = {
        "source_project": "quant_lab",
        "topic": "茅台深度研报",
        "content": "600519 #贵州茅台 深度研报：白酒行业进入存量博弈，但高端品牌溢价依然稳固。",
        "metadata": {"stock_code": "600519"}
    }

    response = httpx.post("http://127.0.0.1:8000/api/v1/wiki/ingest", json=payload_q)
    print(f"✅ Response Status: {response.status_code}")
    print(f"📄 JSON Data: {response.json()}")

    print("\n⏳ Tasks are queued. They will be processed asynchronously in the background.")
    print("Check the terminal where FastAPI is running for logs.")

if __name__ == "__main__":
    test_wiki_ingest_endpoint()
