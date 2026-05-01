import os
import json
import re
import time
import sys
import httpx
from openai import OpenAI
import fitz  # PyMuPDF
import docx  # python-docx
import base64
import shutil
from typing import List, Dict, Any
from urllib.parse import quote
from tenacity import retry, wait_exponential, stop_after_attempt

# ── 导入 WikiService 的 Provider 链（用于消除单点故障） ─────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

try:
    from wiki_service import (
        ProviderConfig, _build_generate_chain,
        NON_RETRYABLE_STATUS
    )
    WIKI_SERVICE_AVAILABLE = True
except ImportError as _e:
    print(f"⚠️ 无法导入 wiki_service Provider 链: {_e}")
    WIKI_SERVICE_AVAILABLE = False

# --- 配置 ---
API_KEYS = [k.strip() for k in (os.getenv("ZHIPUAI_API_KEY") or "").split(",") if k.strip()]
if not API_KEYS:
    API_KEYS = ["dummy"]
BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
MODEL_NAME = "glm-4.7-flash"

# 目标目录：动态获取项目根目录
TARGET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_FILE = os.path.join(TARGET_DIR, "README.md")

# 文件夹管线配置
INCOMING_DIR = os.path.join(TARGET_DIR, "incoming")
ARCHIVE_DIR = os.path.join(TARGET_DIR, "archive")

for d in [INCOMING_DIR, ARCHIVE_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

def extract_chart_insight(base64_image: str) -> str:
    """调用 DeepSeek-OCR 获取图表内容 (带退避重试)"""
    sf_key = os.getenv("SILICONFLOW_API_KEY")
    if not sf_key:
        return ""
    
    prompt = "请提取并描述这张图表或图片中的核心数据和洞察。请使用Markdown格式。如果是无意义的插图（如背景、公司Logo、纯装饰），请回复'无关键信息'。"
    
    # 因为 OCR 耗时较长，增加超时时间
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.siliconflow.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {sf_key}"},
            json={
                "model": "deepseek-ai/DeepSeek-OCR",
                "messages": [
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                        {"type": "text", "text": prompt}
                    ]}
                ]
            }
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        if "无关键信息" in content:
            return ""
        return content

# 包装重试逻辑，隔离出单次请求
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
def safe_extract_chart_insight(base64_image: str) -> str:
    return extract_chart_insight(base64_image)


# ── 同步版 JSON 解析与 LLM 调用（复用 wiki_service 的 Provider 链） ─────────

def _extract_json_sync(raw_text: str) -> Dict[str, Any]:
    """多策略提取 JSON，处理大模型各种包裹格式"""
    try:
        return json.loads(raw_text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    match = re.search(r'```[jJ][sS][oO][nN]?\s*\n(.*?)\n\s*```', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError(f"Cannot parse JSON from: {raw_text[:200]}")


def _call_llm_json_sync(
    system_prompt: str,
    user_content: str,
    max_retries: int = 3,
    providers: List[ProviderConfig] = None,
) -> Dict[str, Any]:
    """
    同步版 LLM 调用，遍历 Provider 优先级链，集成 Circuit Breaker。
    供 ai_organizer.py 在文档分析阶段使用。
    """
    if not providers:
        raise RuntimeError("No LLM providers configured.")

    last_error = None
    skipped = []

    with httpx.Client(timeout=120.0) as client:
        for provider in providers:
            if not provider.is_available:
                skipped.append(provider.name)
                continue

            for attempt in range(max_retries):
                try:
                    resp = client.post(
                        f"{provider.api_base}/chat/completions",
                        headers={"Authorization": f"Bearer {provider.current_key}"},
                        json={
                            "model": provider.model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_content}
                            ]
                        },
                    )

                    # 不可重试错误 → 直接跳到下一个 Provider
                    if resp.status_code in NON_RETRYABLE_STATUS:
                        print(f"  ⚠️  [{provider.name}] Non-retryable {resp.status_code}: {resp.text[:150]}. Skipping...")
                        provider.mark_failed()
                        break

                    # 429 Rate Limit → 轮换 Key + 指数退避
                    if resp.status_code == 429:
                        print(f"  ⚠️  [{provider.name}] 429 Rate Limit. Rotating key...")
                        provider.rotate_key()
                        time.sleep(2 * (attempt + 1))
                        continue

                    # 其他非 200 错误
                    if resp.status_code != 200:
                        print(f"  ⚠️  [{provider.name}] API Error {resp.status_code}: {resp.text[:200]}")
                        resp.raise_for_status()

                    # ✅ 成功 → 重置熔断器
                    provider.mark_success()
                    raw_text = resp.json()["choices"][0]["message"]["content"]
                    return _extract_json_sync(raw_text)

                except Exception as e:
                    last_error = e
                    print(f"  ⚠️  [{provider.name}] Attempt {attempt+1}/{max_retries} failed: {e}")
                    if attempt < max_retries - 1:
                        provider.rotate_key()
                        time.sleep(2)

            # 当前 Provider 已耗尽所有重试 → 标记失败并降级
            provider.mark_failed()
            print(f"  ⚠️  [{provider.name}] Exhausted. Falling back to next provider...")

    if skipped:
        print(f"  ℹ️  Skipped providers in cooldown: {', '.join(skipped)}")

    raise RuntimeError(f"All providers exhausted. Last error: {last_error}")

def extract_text_from_pdf(filepath):
    """使用 PyMuPDF 进行混合提取：原生文字 + 原生表格 + 智能图表 OCR"""
    text_parts = []
    try:
        doc = fitz.open(filepath)
        for page_num, page in enumerate(doc):
            page_text = []
            
            # 1. 提取原生表格 (PyMuPDF find_tables)
            tables = page.find_tables()
            if tables:
                for tab in tables:
                    try:
                        md_table = tab.to_markdown()
                        if md_table:
                            page_text.append("[原生表格数据]:\n" + md_table)
                    except Exception:
                        pass
                        
            # 2. 提取文本块
            blocks = page.get_text("blocks")
            for b in blocks:
                if b[6] == 0:  # text block
                    content = b[4].strip()
                    if content and not content.isdigit():
                        page_text.append(content)
            
            # 3. 处理图片 (交由 DeepSeek-OCR)
            images = page.get_images(full=True)
            for img_index, img in enumerate(images):
                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    # 如果不是RGB或灰度图，先转换
                    if pix.n - pix.alpha > 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    
                    # 过滤掉过小的图标或Logo (小于 100x100)
                    if pix.width < 100 or pix.height < 100:
                        continue
                        
                    img_bytes = pix.tobytes("jpeg")
                    b64_img = base64.b64encode(img_bytes).decode('utf-8')
                    
                    print(f"  🔍 发现图表 (页码 {page_num+1})，正在交由 DeepSeek-OCR 分析...")
                    insight = safe_extract_chart_insight(b64_img)
                    if insight:
                        page_text.append(f"[图表/图片解析]:\n{insight}")
                except Exception as e:
                    print(f"  ⚠️ 图表 OCR 失败: {e}")
                    
            if page_text:
                text_parts.append("\n\n".join(page_text))
        doc.close()
    except Exception as e:
        print(f"❌ 读取PDF失败 {filepath}: {e}")
        return None
    
    # 组合全篇并截断防止超载
    return "\n\n---\n\n".join(text_parts)[:100000]

def extract_text_from_docx(filepath):
    """使用 python-docx 提取Word文本 (全篇读取)"""
    text = []
    try:
        doc = docx.Document(filepath)
        for para in doc.paragraphs:
            if para.text.strip():
                text.append(para.text)
        return "\n".join(text)[:100000]
    except Exception as e:
        print(f"❌ 读取DOCX失败 {filepath}: {e}")
        return None

def extract_text_from_md(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()[:100000]
    except Exception as e:
        print(f"❌ 读取MD失败 {filepath}: {e}")
        return None

def extract_text_from_image(filepath):
    try:
        with open(filepath, 'rb') as f:
            b64_img = base64.b64encode(f.read()).decode('utf-8')
        print(f"  🔍 发现单独图片文件，正在交由 DeepSeek-OCR 分析...")
        insight = safe_extract_chart_insight(b64_img)
        if insight:
            return f"[图片原生解析]:\n{insight}"
        return "无关键信息"
    except Exception as e:
        print(f"❌ 读取图片失败 {filepath}: {e}")
        return None

def extract_text_from_pptx(filepath):
    try:
        from pptx import Presentation
        prs = Presentation(filepath)
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    text.append(shape.text.strip())
        return "\n".join(text)[:100000]
    except Exception as e:
        print(f"❌ 读取PPTX失败 {filepath}: {e}")
        return None

def extract_text_from_xlsx(filepath):
    try:
        import pandas as pd
        # Read all sheets into a dict of DataFrames
        xls = pd.read_excel(filepath, sheet_name=None)
        text_parts = []
        for sheet_name, df in xls.items():
            text_parts.append(f"### 表格页: {sheet_name}")
            text_parts.append(df.to_markdown(index=False))
        return "\n\n".join(text_parts)[:100000]
    except Exception as e:
        print(f"❌ 读取XLSX失败 {filepath}: {e}")
        return None

def extract_text(filepath):
    """根据文件扩展名分发提取任务"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(filepath)
    elif ext == '.docx':
        return extract_text_from_docx(filepath)
    elif ext == '.md':
        return extract_text_from_md(filepath)
    elif ext in ['.jpg', '.jpeg', '.png']:
        return extract_text_from_image(filepath)
    elif ext == '.pptx':
        return extract_text_from_pptx(filepath)
    elif ext == '.xlsx':
        return extract_text_from_xlsx(filepath)
    return None

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def analyze_content(text, original_filename):
    """调用 LLM 分析内容并评分 (支持重试与 CoT 思维链)"""
    prompt = f"""
    你是一个严谨的金融与科技文档资深分析师。请基于以下文档的**完整内容**进行深度剖析。
    请务必通读全部提供的内容（可能包含几十页），不要只看开头，确保摘要涵盖报告的核心数据、论证和最终结论。
    
    文件名: {original_filename}
    文档内容:
    {text}
    
    请提取以下信息并以纯 JSON 格式返回:
    1. thinking_process: 请先在此字段中写下你的分析思路。比如：“这份报告主要讨论了X...我看到第N段提到了核心数据Y...结论是Z...”。这会帮助你理清逻辑，避免幻觉。
    2. tags: 提取 2-3 个最核心的领域/主题标签 (如: 量子计算, 核聚变, 商业航天, 军工, 机械)。
    3. title: 一个简短、标准化的标题 (去除"发现报告"等无关注缀，去除文件名中的日期)。
    4. institution: 发布机构 (如: 浙商证券, 中移智库)。
    5. year: 发布年份 (YYYY)。
    6. summary: 生成一份深度摘要，字数不少于300字。内容必须包含以下三个部分：
       - 【核心论点】：阐述报告的主要观点。
       - 【支持证据】：列举报告中引用的关键数据、案例或逻辑推导。
       - 【结论与建议】：总结报告的最终结论及投资/行动建议。
    7. score: 资料可信度及价值打分 (1-10分)。请严格遵循正态分布原则，拒绝平均主义：
       - 9-10分：顶级报告，数据极其详实，逻辑严密，有独家洞见。
       - 7-8分：优秀报告，内容扎实，但创新性或深度略逊。
       - 5-6分：普通报告，主要是信息罗列，缺乏深度分析。
       - 1-4分：劣质报告，内容空洞，或仅为营销软文。
    8. score_reason: 用一句话简述打分理由，直击要害（例如：“数据来源权威且分析模型严谨”或“仅为概念堆砌，缺乏实证支持”）。
    
    JSON 格式示例:
    {{
        "thinking_process": "首先，我通读了全文，发现这份报告的核心是在讨论量子计算在生物制药中的应用。文章在中间部分提供了三个具体的行业案例数据...最后结论建议...",
        "tags": ["量子计算", "生物制药"],
        "title": "量子计算在生物制药产业的发展研究",
        "institution": "中移智库",
        "year": "2025",
        "summary": "【核心论点】本报告深入分析了... \\n\\n【支持证据】数据显示... \\n\\n【结论与建议】建议关注...",
        "score": 7.2,
        "score_reason": "框架完整但缺乏一手数据支持"
    }}
    """

    # ── 路径 1: 使用 Provider 链（消除单点故障） ───────────────────────
    if WIKI_SERVICE_AVAILABLE:
        providers = _build_generate_chain()
        if providers:
            try:
                print(f"🔄 使用 Provider 链分析文档: {' → '.join([p.name for p in providers])}")
                return _call_llm_json_sync(
                    system_prompt="你是一个只输出 JSON 的文档分析助手。",
                    user_content=prompt,
                    providers=providers
                )
            except Exception as e:
                print(f"⚠️  Provider 链全部失败: {e}")
                print("  回退到硬编码 ZhipuAI...")
        else:
            print("⚠️  未配置 Provider 链 API Key，回退到硬编码 ZhipuAI...")
    else:
        print("⚠️  wiki_service 不可用，使用硬编码 ZhipuAI...")

    # ── 路径 2: 硬编码 ZhipuAI（最终兜底） ─────────────────────────────
    import random
    selected_key = random.choice(API_KEYS)
    local_client = OpenAI(api_key=selected_key, base_url=BASE_URL)

    try:
        response = local_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个只输出 JSON 的文档分析助手。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        content = response.choices[0].message.content
        return json.loads(content, strict=False)
    except Exception as e:
        print(f"❌ AI 分析失败或触发限流 (准备重试...): {e}")
        raise e  # 抛出异常以触发 tenacity 的重试机制

def update_index_file(entry):
    """更新 README.md 索引 (清单式布局)"""
    if not os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            f.write("# 知识库深度索引 (Deep Knowledge Base Index)\n\n")
            f.write("> 本索引由 AI 自动生成，包含每份报告的深度摘要、评分及核心观点。\n\n")
            f.write("---\n\n")

    tags_str = " ".join([f"`{t}`" for t in entry['tags']])
    score = entry.get('score', 'N/A')
    reason = entry.get('score_reason', '暂无理由')
    summary = entry.get('summary', '暂无摘要')
    
    # 格式化摘要
    summary = summary.replace("【", "**【").replace("】", "】**")
    
    # 链接使用相对路径指向 archive 文件夹
    link = quote(f"archive/{entry['filename']}")
    
    # 构建卡片式内容
    lines = [
        f"### [{score}] [{entry['title']}]({link})",
        f"",
        f"> **机构**: {entry['institution']} | **年份**: {entry['year']} | **标签**: {tags_str}",
        f">",
        f"> **评分理由**: _{reason}_",
        f"",
        f"{summary}",
        f"",
        f"---",
        f""
    ]
    
    with open(INDEX_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def process_directory():
    doc_files = []
    # 扫描所有支持的格式
    valid_extensions = ('.pdf', '.docx', '.md', '.jpg', '.jpeg', '.png', '.pptx', '.xlsx')
    
    # 只扫描 INCOMING_DIR
    for root, dirs, files in os.walk(INCOMING_DIR):
        for file in files:
            if file.lower().endswith(valid_extensions):
                doc_files.append(os.path.join(root, file))
    
    print(f"📂 在待处理区(incoming)发现 {len(doc_files)} 个文档...")
    
    # 读取现有的 README 内容，用于去重
    existing_content = ""
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            existing_content = f.read()

    for filepath in doc_files:
        filename = os.path.basename(filepath)
        
        # --- 智能增量更新逻辑 ---
        encoded_filename = quote(filename)
        if encoded_filename in existing_content:
            # 只有当文件确实在 README 中时才跳过
            print(f"⏭️  已索引，跳过: {filename}")
            continue
            
        print(f"\nProcessing New File: {filename} ...")
        
        # 统一的文本提取接口
        text = extract_text(filepath)
        if not text:
            continue

        try:
            meta = analyze_content(text, filename)
        except Exception as e:
            print(f"❌ 文档分析失败，跳过: {filename} | 错误: {e}")
            continue

        if not meta:
            print(f"⏭️  分析返回空结果，跳过: {filename}")
            continue
            
        tags_slug = "_".join(meta['tags'][:2])
        safe_title = re.sub(r'[\\/*?:"<>|]', "", meta['title'])
        safe_inst = re.sub(r'[\\/*?:"<>|]', "", meta['institution'])
        
        # 年份保底逻辑
        year = str(meta.get('year', '2025')).strip()
        year_match = re.search(r'\d{4}', year)
        if year_match:
            year = year_match.group(0)
        else:
            year = '2025'
        
        # 获取原始扩展名
        _, ext = os.path.splitext(filename)
        
        new_filename = f"[{tags_slug}]_{year}_{safe_inst}_{safe_title}{ext}"
        new_filename = new_filename.replace(" ", "_")
        
        # 目标归档路径
        new_filepath = os.path.join(ARCHIVE_DIR, new_filename)
        
        # 移动并重命名文件
        try:
            shutil.move(filepath, new_filepath)
            print(f"✅ Moved & Renamed to Archive: {new_filename}")
            meta['filename'] = new_filename
        except Exception as e:
            print(f"⚠️ 文件移动失败 {filename}: {e}")
            meta['filename'] = filename

        # --- 投递摘要至 WikiAgent ---
        wiki_payload = {
            "source_project": "pdf_archive",
            "topic": meta['title'],
            "content": meta['summary'],
            "metadata": {
                "tags": meta.get('tags', []),
                "institution": meta.get('institution', '未知机构'),
                "year": meta.get('year', '2025'),
                "score": meta.get('score', 0),
                "score_reason": meta.get('score_reason', ''),
                "original_file": meta['filename']
            }
        }
        
        try:
            httpx.post("http://127.0.0.1:8000/api/v1/wiki/ingest", json=wiki_payload, timeout=10)
            print(f"🚀 已成功将 {meta['title']} 的知识条目推送到 WikiAgent 队列！")
        except Exception as e:
            print(f"⚠️ 推送 WikiAgent 失败 (请确保 uvicorn api:app 正在运行): {e}")

        update_index_file(meta)
        time.sleep(1)

if __name__ == "__main__":
    process_directory()
