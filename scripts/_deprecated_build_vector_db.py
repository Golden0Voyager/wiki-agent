import os
import glob
import shutil
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from tqdm import tqdm

# --- 配置 ---
KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(KB_ROOT, "chroma_db")
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"

def main():
    print(f"🚀 开始构建知识库向量索引...")
    print(f"📂 知识库根目录: {KB_ROOT}")
    print(f"💾 数据库路径: {DB_PATH}")

    # 0. 询问是否重建
    if os.path.exists(DB_PATH):
        print(f"⚠️ 检测到已存在数据库: {DB_PATH}")
        choice = input("是否删除旧库并重建？(y/n) [默认 n]: ").strip().lower()
        if choice == 'y':
            shutil.rmtree(DB_PATH)
            print("🗑️ 旧数据库已删除")
        else:
            print("ℹ️ 将在现有数据库上追加内容")

    # 1. 扫描 PDF 文件
    # 匹配 [Tag]... 格式的文件
    pdf_files = glob.glob(os.path.join(KB_ROOT, "[[]*.pdf")) 
    print(f"📄 发现 {len(pdf_files)} 个符合规范的 PDF 文件")

    if not pdf_files:
        print("⚠️ 未找到符合规范的文件，请检查文件名是否以 '[' 开头")
        return

    # 2. 初始化 Embedding 模型
    print(f"⬇️ 加载 Embedding 模型 ({EMBEDDING_MODEL})...")
    print("   (初次运行会自动下载模型权重，约 90MB，请耐心等待)")
    
    # 尝试使用 MPS (Metal Performance Shaders) 加速，如果不可用则回退到 CPU
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"⚡️ 使用计算设备: {device.upper()}")

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'device': device},
        encode_kwargs={'normalize_embeddings': True}
    )

    # 3. 处理文档
    all_splits = []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]
    )

    print("✂️ 开始读取并切分文档...")
    for pdf_path in tqdm(pdf_files, desc="Processing PDFs"):
        try:
            filename = os.path.basename(pdf_path)
            
            loader = PyPDFLoader(pdf_path)
            docs = loader.load()
            
            # 为每个切片添加源文件元数据
            for doc in docs:
                doc.metadata["source"] = filename
                # doc.metadata["path"] = pdf_path # 路径可能变，只存相对路径或文件名更稳妥
            
            splits = text_splitter.split_documents(docs)
            all_splits.extend(splits)
            
        except Exception as e:
            print(f"\n❌ 处理文件失败: {filename}")
            print(f"   错误信息: {str(e)}")

    if not all_splits:
        print("⚠️ 没有提取到任何文本内容。 ולא נמצאה כל תוכן טקסט.")
        return

    print(f"✅ 共生成 {len(all_splits)} 个知识切片，准备写入数据库...")

    # 4. 存入 ChromaDB
    # batch_size 限制每次写入的数量，防止内存溢出
    batch_size = 5000 
    total_splits = len(all_splits)
    
    for i in range(0, total_splits, batch_size):
        batch = all_splits[i : i + batch_size]
        print(f"💾 写入批次 {i//batch_size + 1}/{total_splits//batch_size + 1} ({len(batch)} chunks)...")
        Chroma.from_documents(
            documents=batch,
            embedding=embeddings,
            persist_directory=DB_PATH
        )
    
    print(f"🎉 知识库构建完成！已保存到 {DB_PATH}")
    print(f"🔍 现在你可以编写查询脚本来搜索这 {total_splits} 个知识片段了。 ולאחר מכן תוכל לכתוב סקריפט שאילתה כדי לחפש את {total_splits} קטעי הידע הללו.")

if __name__ == "__main__":
    main()
