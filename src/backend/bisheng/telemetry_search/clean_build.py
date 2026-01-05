import os
import sys

# 1. 定义需要清理的文件后缀
# .c   : Cython 生成的中间 C 代码
# .so  : Linux/Mac 编译好的动态库
# .pyd : Windows 编译好的动态库
# .html: 如果你使用了 annotation=True 生成的代码分析文件
TARGET_EXTENSIONS = {'.c', '.so', '.pyd'}

# 2. 定义黑名单目录（绝对不清理这些目录下的文件）
# 必须包含 venv 环境，防止误删第三方库的编译文件
IGNORE_DIRS = {
    'venv', '.venv', '.git', '.idea', '.vscode', '__pycache__',
    'build', 'dist', 'node_modules'
}


def clean_project():
    deleted_count = 0

    print(f"正在扫描目录: {os.getcwd()} ...")
    print(f"将清理以下后缀的文件: {TARGET_EXTENSIONS}")
    print("-" * 30)

    for root, dirs, files in os.walk("."):
        # 修改 dirs 列表，原地过滤掉不需要遍历的目录
        # 这一步非常重要，防止钻进 venv 里误删
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in IGNORE_DIRS]

        for file in files:
            # 获取文件后缀
            _, ext = os.path.splitext(file)

            if ext in TARGET_EXTENSIONS:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    print(f"[已删除] {file_path}")
                    deleted_count += 1
                except Exception as e:
                    print(f"[删除失败] {file_path} - {e}")

    print("-" * 30)
    if deleted_count == 0:
        print("未发现需要清理的文件。")
    else:
        print(f"清理完成，共删除了 {deleted_count} 个文件。")


if __name__ == "__main__":
    # 添加二次确认，防止手滑
    while True:
        confirm = input("⚠️  警告：这将删除当前目录下所有的编译产物 (.c, .so, .pyd)。\n确认要继续吗？(y/n): ").lower()
        if confirm in ('y', 'yes'):
            clean_project()
            break
        elif confirm in ('n', 'no'):
            print("操作已取消。")
            break