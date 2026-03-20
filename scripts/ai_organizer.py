import os
import json
import re
import time
from openai import OpenAI
import fitz  # PyMuPDF
import docx  # python-docx
from urllib.parse import quote

# --- 配置 ---
API_KEY = os.getenv("ZHIPUAI_API_KEY") 
BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
MODEL_NAME = "glm-4.6v-flash"

# 目标目录：动态获取项目根目录
TARGET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX_FILE = os.path.join(TARGET_DIR, "README.md")

client = OpenAI(
    api_key=API_KEY if API_KEY else "dummy",
    base_url=BASE_URL
)

def extract_text_from_pdf(filepath, max_pages=5):
    """使用 PyMuPDF 提取PDF文本"""
    text = ""
    try:
        doc = fitz.open(filepath)
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text += page.get_text()
        doc.close()
    except Exception as e:
        print(f"❌ 读取PDF失败 {filepath}: {e}")
        return None
    return text[:8000]

def extract_text_from_docx(filepath):
    """使用 python-docx 提取Word文本"""
    text = []
    try:
        doc = docx.Document(filepath)
        # 提取段落文本
        for para in doc.paragraphs:
            if para.text.strip():
                text.append(para.text)
            # 简单限制长度，避免提取过多
            if len(text) > 200: # 大约200段
                break
        return "\n".join(text)[:8000]
    except Exception as e:
        print(f"❌ 读取DOCX失败 {filepath}: {e}")
        return None

def extract_text(filepath):
    """根据文件扩展名分发提取任务"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(filepath)
    elif ext == '.docx':
        return extract_text_from_docx(filepath)
    return None

def analyze_content(text, original_filename):
    """调用 LLM 分析内容并评分"""
    prompt = f"""
    你是一个严谨的金融与科技文档资深分析师。请基于以下文档内容进行深度剖析。
    
    文件名: {original_filename}
    文档内容预览:
    {text}
    
    请提取以下信息并以纯 JSON 格式返回:
    1. tags: 提取 2-3 个最核心的领域/主题标签 (如: 量子计算, 核聚变, 商业航天, 军工, 机械)。
    2. title: 一个简短、标准化的标题 (去除"发现报告"等无关注缀，去除文件名中的日期)。
    3. institution: 发布机构 (如: 浙商证券, 中移智库)。
    4. year: 发布年份 (YYYY)。
    5. summary: 生成一份深度摘要，字数不少于300字。内容必须包含以下三个部分：
       - 【核心论点】：阐述报告的主要观点。
       - 【支持证据】：列举报告中引用的关键数据、案例或逻辑推导。
       - 【结论与建议】：总结报告的最终结论及投资/行动建议。
    6. score: 资料可信度及价值打分 (1-10分)。请严格遵循正态分布原则，拒绝平均主义：
       - 9-10分：顶级报告，数据极其详实，逻辑严密，有独家洞见。
       - 7-8分：优秀报告，内容扎实，但创新性或深度略逊。
       - 5-6分：普通报告，主要是信息罗列，缺乏深度分析。
       - 1-4分：劣质报告，内容空洞，或仅为营销软文。
    7. score_reason: 用一句话简述打分理由，直击要害（例如：“数据来源权威且分析模型严谨”或“仅为概念堆砌，缺乏实证支持”）。
    
    JSON 格式示例:
    {{
        "tags": ["量子计算", "生物制药"],
        "title": "量子计算在生物制药产业的发展研究",
        "institution": "中移智库",
        "year": "2025",
        "summary": "【核心论点】本报告深入分析了... \\n\\n【支持证据】数据显示... \\n\\n【结论与建议】建议关注...",
        "score": 7.2,
        "score_reason": "框架完整但缺乏一手数据支持"
    }}
    """
    
    try:
        response = client.chat.completions.create(
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
        print(f"❌ AI 分析失败: {e}")
        return None

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
    
    link = quote(entry['filename'])
    
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
    # 同时扫描 .pdf 和 .docx
    valid_extensions = ('.pdf', '.docx')
    
    for root, dirs, files in os.walk(TARGET_DIR):
        for file in files:
            if file.lower().endswith(valid_extensions):
                doc_files.append(os.path.join(root, file))
    
    print(f"📂 发现 {len(doc_files)} 个支持的文档 (PDF/DOCX)...")
    
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
        if not text: continue
            
        meta = analyze_content(text, filename)
        if not meta: continue
            
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
        
        # 获取原始扩展名 (.pdf 或 .docx)
        _, ext = os.path.splitext(filename)
        
        new_filename = f"[{tags_slug}]_{year}_{safe_inst}_{safe_title}{ext}"
        new_filename = new_filename.replace(" ", "_")
        
        parent_dir = os.path.dirname(filepath)
        new_filepath = os.path.join(parent_dir, new_filename)
        
        if filepath != new_filepath:
            if not os.path.exists(new_filepath):
                os.rename(filepath, new_filepath)
                print(f"✅ Renamed: {new_filename}")
                meta['filename'] = new_filename
            else:
                meta['filename'] = new_filename
        else:
            meta['filename'] = filename

        update_index_file(meta)
        time.sleep(1)

if __name__ == "__main__":
    process_directory()
