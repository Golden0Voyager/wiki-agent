import hashlib
import os
import re

TARGET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def get_file_hash(filepath):
    """计算文件的 MD5 哈希值"""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def clean_duplicates():
    # 收集所有 PDF 文件
    all_files = []
    for root, dirs, files in os.walk(TARGET_DIR):
        for file in files:
            if file.lower().endswith(".pdf"):
                all_files.append(os.path.join(root, file))

    print(f"🔍 扫描了 {len(all_files)} 个文件...")

    # 哈希映射: hash -> list of filepaths
    hash_map = {}
    for filepath in all_files:
        file_hash = get_file_hash(filepath)
        if file_hash:
            if file_hash not in hash_map:
                hash_map[file_hash] = []
            hash_map[file_hash].append(filepath)

    deleted_count = 0

    # 遍历哈希组，处理重复
    for file_hash, paths in hash_map.items():
        if len(paths) > 1:
            print(f"\n发现重复组 (Hash: {file_hash[:8]}...):")
            # 排序策略：
            # 1. 优先保留以 '[' 开头的文件（AI 整理过的）。
            # 2. 其次保留文件名更短的（通常没有 (1) 后缀）。
            # 3. 再次按路径长度排序（根目录优先）。

            def sort_key(path):
                filename = os.path.basename(path)
                is_tagged = filename.startswith("[")
                # 我们希望 is_tagged 为 True 的排在前面 (False < True, 所以要反过来或者用负数)
                # 实际上 Python sort 是升序。False=0, True=1.
                # 我们希望 True 排在前面，所以用 -1 * True = -1, -1 * False = 0.

                # 还有文件名里有 (1) 的应该排在后面。
                has_copy_mark = bool(re.search(r'\(\d+\)', filename))

                return (not is_tagged, has_copy_mark, len(filename))

            paths.sort(key=sort_key)

            keep = paths[0]
            remove_list = paths[1:]

            print(f"  ✅ 保留: {os.path.basename(keep)}")
            for p in remove_list:
                print(f"  ❌ 删除: {os.path.basename(p)}")
                try:
                    os.remove(p)
                    deleted_count += 1
                except Exception as e:
                    print(f"    删除失败: {e}")

    print(f"\n✨ 清理完成。共删除了 {deleted_count} 个重复文件。")

if __name__ == "__main__":
    clean_duplicates()
