#!/bin/bash
# 使用方式1： bash patch_code.sh conda环境名
# 脚本将尝试进入conda环境

# 使用方式2： bash patch_code.sh
# 不使用conda环境，请确认执行脚本前，已经进入项目python环境中

# 将 Windows 路径转换为 Git Bash 路径
win_to_gitbash_path() {
    local path="$1"

    # 检查是否是 Windows 路径格式（包含反斜杠 '\'）
    if [[ "$path" == *\\* ]]; then
        # 替换盘符 C:\ -> /c/
        path=$(echo "$path" | sed -E 's/^([A-Za-z]):\\/\L\/\1\//')

        # 将反斜杠 \ 替换为正斜杠 /
        path=$(echo "$path" | sed 's/\\/\//g')
    fi

    echo "$path"
}

# 检查命令是否存在
check_command() {
  if ! command -v $1  &> /dev/null; then
    echo "检测到命令缺失，请先安装：$1"
    exit 1
  fi
}


patch_code_file() {
  patch_file="$1"
  code_file="$2"
  search_pattern="$3"
  if [ -f "$code_file" ]; then
      # 执行 grep 并捕获输出
      if output=$(grep -n "$search_pattern" "$code_file" 2>&1); then
          echo "源代码可能已经存在该补丁，请勿重复应用，跳过：$code_file"
      else
          echo "准备打补丁"
          patch -p1 < "$patch_file" "$code_file"
          echo "补丁应用成功"
      fi
  else
      echo "补丁文件没找到，可能你的环境未安装相应依赖： $code_file"
  fi
}



check_command patch
check_command dirname

cpath="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ "$#" -ge 1 ]; then
  echo "尝试进入conda环境"
  check_command conda
  we_conda_path=$(conda info --base)
  . "$we_conda_path/etc/profile.d/conda.sh"
  conda activate $1
else
    echo "没有传递conda环境名称，将使用默认python环境"
    echo "请确认执行脚本前，已经进入项目python环境中"
fi

check_command python


#python_path=$(python -c 'import os; print(os.environ["CONDA_PREFIX"])')
python_path=$(python -c 'from distutils.sysconfig import get_python_lib; print(get_python_lib())')
python_path=$(win_to_gitbash_path "$python_path")

echo "检测到python环境依赖目录：$python_path"

patch_code_file "$cpath/bisheng/patches/fastapi_jwt_auth.patch" "$python_path/fastapi_jwt_auth/config.py" str_min_length
patch_code_file "$cpath/bisheng/patches/langchain_openai.patch" "$python_path/langchain_openai/chat_models/base.py" "additional_kwargs\['reasoning_content'\]"


