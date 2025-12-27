import os
import shutil

TARGET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def flatten_directory():
    print(f"开始扁平化目录: {TARGET_DIR}")
    
    moved_count = 0
    
    # 遍历所有子目录
    for root, dirs, files in os.walk(TARGET_DIR, topdown=False):
        # 跳过根目录本身
        if root == TARGET_DIR:
            continue
            
        for file in files:
            if file.lower().endswith(".pdf") or file.endswith(".md"): # 移动 PDF 和 md (如果有)
                src_path = os.path.join(root, file)
                dst_path = os.path.join(TARGET_DIR, file)
                
                # 如果目标文件已存在，为了避免覆盖，先重命名一下源文件
                if os.path.exists(dst_path):
                    base, ext = os.path.splitext(file)
                    dst_path = os.path.join(TARGET_DIR, f"{base}_conflict{ext}")
                
                print(f"Moving: {file} -> root")
                shutil.move(src_path, dst_path)
                moved_count += 1
        
        # 尝试删除空目录
        try:
            os.rmdir(root)
            print(f"Removed empty dir: {root}")
        except OSError:
            # 目录非空，跳过
            pass

    print(f"扁平化完成。移动了 {moved_count} 个文件。")

if __name__ == "__main__":
    flatten_directory()
