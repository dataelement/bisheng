import os
import re
from typing import Tuple, List, Dict, Any, Optional

import aiofiles
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from bisheng_langchain.linsight.utils import format_size


class FileToolInput(BaseModel):
    file_path: str = Field(..., description="要查看的目录路径,默认为当前目录")


class FileDirToolInput(BaseModel):
    directory_path: str = Field(..., description="文件的完整路径")


class SearchFilesInput(BaseModel):
    directory_path: str = Field(..., description="要搜索的目录路径")
    pattern: Optional[str] = Field(default=None, description="文件名匹配的正则表达式模式（可选）")
    max_depth: Optional[int] = Field(default=5, description="最大递归深度（可选，默认为5）")


class ReadFileInput(BaseModel):
    file_path: str = Field(..., description="要读取的文件路径")
    start_line: Optional[int] = Field(default=1, description="起始行号（从1开始计数）")
    num_lines: Optional[int] = Field(default=50, description="需要读取的行数，最多50行")


class SearchTextInput(BaseModel):
    file_path: str = Field(..., description="要搜索的文件路径")
    keyword: str = Field(..., description="要搜索的短关键词(基于完全匹配)")
    result_index: Optional[int] = Field(default=0, description="要返回的匹配结果索引（从0开始计数），默认为第一个匹配")
    context_lines: Optional[int] = Field(default=25, description="显示匹配关键词前后的行数，默认为25行")


class WriteFileInput(BaseModel):
    file_path: str = Field(..., description="目标文件路径")
    content: str = Field(..., description="要写入的内容")
    start_line: Optional[int] = Field(default=-1,
                                      description="开始写入的行号（1-based）。-1 表示追加，0 表示从头覆盖，正数表示插入")


class ReplaceFileInput(BaseModel):
    file_path: str = Field(..., description="要编辑的文件路径")
    start_line: int = Field(..., description="开始替换的行号（从1开始计数，包含此行）")
    end_line: int = Field(..., description="结束替换的行号（从1开始计数，不包含此行，左开右闭区间）")
    replacement_text: str = Field(..., description="替换的文本内容")


class LocalFileTool(BaseModel):
    """
    LocalFileTool is a tool for managing local files.
    It provides methods to read, write, and delete files.
    """
    root_path: str = Field(..., description="Root path for file operations permission")

    def validate_file_path(self, file_path: str) -> Tuple[bool, str, str]:
        """
        验证文件路径是否在允许的目录范围内

        Args:
            file_path: 要验证的文件路径

        Returns:
            Tuple[bool, str, str]: (是否有效, 规范化后的路径, 错误信息)
        """
        try:
            # 如果是相对路径，则拼接到默认根目录
            if not os.path.isabs(file_path):
                normalized_path = os.path.join(self.root_path, file_path)
            else:
                normalized_path = file_path

            # 获取规范化的绝对路径
            normalized_path = os.path.abspath(normalized_path)
            root_path = os.path.abspath(self.root_path)

            # 检查路径是否在允许的根目录下
            if not normalized_path.startswith(root_path):
                return False, "", f"没有权限访问 '{file_path}'，路径超出允许范围"
            return True, normalized_path, ""
        except Exception as e:
            return False, "", f"路径验证失败: {str(e)}"

    def list_files(self, directory_path: str) -> List[str]:
        """
        列出指定目录下的所有文件和子目录

        Args:
            directory_path: 要查看的目录路径,默认为当前目录

        Returns:
            目录中所有文件和子目录的列表
        """
        try:
            # 验证路径权限
            is_valid, normalized_path, error_msg = self.validate_file_path(directory_path)
            if not is_valid:
                return [f"错误: {error_msg}"]

            directory_path = normalized_path

            # 确保路径存在
            if not os.path.exists(directory_path):
                return [f"错误: 路径 '{directory_path}' 不存在"]

            if not os.path.isdir(directory_path):
                return [f"错误: '{directory_path}' 不是一个目录"]

            if directory_path == ".":
                directory_path = os.getcwd()

            # 获取目录内容
            items = os.listdir(directory_path)

            # 构建结果列表，标记文件和目录
            result = []
            for item in items:
                full_path = os.path.join(directory_path, item)
                if os.path.isdir(full_path):
                    result.append({
                        "type": "directory",
                        "name": item,
                        "path": full_path
                    })
                else:
                    # 获取文件大小
                    size = os.path.getsize(full_path)
                    size_str = format_size(size)
                    result.append({
                        "type": "file",
                        "name": item,
                        "size": size_str
                    })

            if not result:
                return ["目录为空"]

            return result

        except Exception as e:
            return [f"发生错误: {str(e)}"]

    def get_file_details(self, file_path: str) -> Dict[str, Any]:
        """
        获取指定文件的详细信息

        Args:
            file_path: 文件的完整路径

        Returns:
            包含文件详细信息的字典
        """
        try:
            # 验证路径权限
            is_valid, normalized_path, error_msg = self.validate_file_path(file_path)
            if not is_valid:
                return {"error": error_msg}

            file_path = normalized_path

            if not os.path.exists(file_path):
                return {"error": f"文件 '{file_path}' 不存在"}

            stats = os.stat(file_path)

            return {
                "名称": os.path.basename(file_path),
                "路径": file_path,
                "大小": format_size(stats.st_size),
                "大小(字节)": stats.st_size,
                "修改时间": stats.st_mtime,
                "是目录": os.path.isdir(file_path),
                "是文件": os.path.isfile(file_path)
            }
        except Exception as e:
            return {"error": str(e)}

    def search_files(self, directory_path: str, pattern: str = "", max_depth: int = 5) -> List[str]:
        """
        在指定目录中搜索文件和子目录

        Args:
            directory_path: 要搜索的目录路径
            pattern: 文件名匹配的正则表达式模式（可选）
            max_depth: 最大递归深度（可选，默认为5）

        Returns:
            匹配的文件和目录列表
        """
        results = []

        try:
            # 验证路径权限
            is_valid, normalized_path, error_msg = self.validate_file_path(directory_path)
            if not is_valid:
                return [f"错误: {error_msg}"]

            directory_path = normalized_path

            if not os.path.exists(directory_path) or not os.path.isdir(directory_path):
                return [f"错误: '{directory_path}' 不是有效目录"]

            # 如果提供了pattern，则编译正则表达式
            regex = None
            if pattern:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                except re.error:
                    return [f"错误: '{pattern}' 不是有效的正则表达式"]

            def search_recursive(current_path, current_depth):
                if current_depth > max_depth:
                    return

                try:
                    items = os.listdir(current_path)
                    for item in items:
                        full_path = os.path.join(current_path, item)

                        # 检查文件名是否匹配
                        if not pattern:
                            # 无模式，包含所有文件
                            matched = True
                        else:
                            # 使用正则表达式匹配
                            matched = bool(regex.search(item))

                        if matched:
                            if os.path.isdir(full_path):
                                results.append(f"📁 {full_path}/")
                            else:
                                size = os.path.getsize(full_path)
                                size_str = format_size(size)
                                results.append(f"📄 {full_path} ({size_str})")

                        # 如果是目录，递归搜索
                        if os.path.isdir(full_path):
                            search_recursive(full_path, current_depth + 1)
                except (PermissionError, OSError):
                    # 忽略无法访问的目录
                    pass

            search_recursive(directory_path, 1)

            if not results:
                if pattern:
                    return [f"未找到匹配 '{pattern}' 的文件"]
                else:
                    return ["未找到文件"]

            return results

        except Exception as e:
            return [f"搜索错误: {str(e)}"]

    async def judge_file_can_read(self, file_path: str) -> (bool, Any):
        # 验证路径权限
        is_valid, normalized_path, error_msg = self.validate_file_path(file_path)
        if not is_valid:
            return False, {"error": error_msg}

        file_path = normalized_path

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return False, {"error": f"文件 '{file_path}' 不存在"}

        # 检查是否是文件
        if not os.path.isfile(file_path):
            return False, {"error": f"'{file_path}' 不是一个文件"}

        # 尝试读取文件内容
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                lines = await f.readlines()
                return True, lines
        except UnicodeDecodeError:
            # 如果UTF-8解码失败，尝试其他编码
            try:
                async with aiofiles.open(file_path, 'r', encoding='gbk') as f:
                    lines = await f.readlines()
                    return True, lines
            except UnicodeDecodeError:
                return False, {"error": "无法解码文件内容，可能是二进制文件"}

    async def read_text_file(self, file_path: str, start_line: int = 1, num_lines: int = 50) -> Dict[str, Any]:
        """
        读取本地文本文件的内容

        Args:
            file_path: 要读取的文件路径
            start_line: 起始行号（从1开始计数）
            num_lines: 需要读取的行数，最多50行

        Returns:
            包含文件内容和元数据的字典
        """
        try:
            flag, lines = await self.judge_file_can_read(file_path)
            if not flag:
                return lines

            # 调整起始行（用户输入从1开始，Python从0开始）
            start_idx = max(0, start_line - 1)

            # 计算结束行
            if num_lines > 50:
                num_lines = 50

            end_idx = min(start_idx + num_lines, len(lines))

            # 提取指定行的内容
            selected_lines = lines[start_idx:end_idx]
            content = ''.join(selected_lines)

            # 构建结果
            total_lines = len(lines)
            result = {
                "文件名": os.path.basename(file_path),
                "总行数": total_lines,
                "读取范围": f"{start_line}-{start_idx + len(selected_lines)}",
                "实际读取行数": len(selected_lines),
                "内容": content
            }

            return result
        except Exception as e:
            return {"error": str(e)}

    async def search_text_in_file(self, file_path: str, keyword: str, result_index: int = 0,
                                  context_lines: int = 25) -> Dict[str, Any]:
        """
        这是一个在文本文件中搜索关键词的工具，并返回匹配结果的上下文。关键词需要尽可能短以满足匹配。

        Args:
            file_path: 要搜索的文件路径
            keyword: 要搜索的短关键词(基于完全匹配)
            result_index: 要返回的匹配结果索引（从0开始计数），默认为第一个匹配
            context_lines: 显示匹配关键词前后的行数，默认为25行

        Returns:
            包含搜索结果和上下文的字典，包括匹配总数、当前匹配索引和上下文内容
        """
        try:
            flag, lines = await self.judge_file_can_read(file_path)
            if not flag:
                return lines

            # 查找所有匹配的行
            matches = []
            for i, line in enumerate(lines):
                if keyword in line:
                    matches.append(i)

            # 检查是否有匹配结果
            total_matches = len(matches)
            if total_matches == 0:
                return {
                    "文件名": os.path.basename(file_path),
                    "关键词": keyword,
                    "匹配总数": 0,
                    "内容": f"未找到关键词 '{keyword}'"
                }

            # 检查请求的索引是否有效
            if result_index < 0 or result_index >= total_matches:
                return {
                    "文件名": os.path.basename(file_path),
                    "关键词": keyword,
                    "匹配总数": total_matches,
                    "错误": f"请求的索引 {result_index} 超出范围 (0-{total_matches - 1})"
                }

            # 获取匹配行的索引
            match_line_index = matches[result_index]

            # 计算上下文范围
            start_line = max(0, match_line_index - context_lines)
            end_line = min(len(lines), match_line_index + context_lines + 1)

            # 提取上下文内容
            context = []
            for i in range(start_line, end_line):
                line_number = i + 1  # 用户友好的行号（从1开始）
                line_content = lines[i].rstrip('\n')

                # 标记匹配行
                if i == match_line_index:
                    line_prefix = f">> {line_number}: "
                else:
                    line_prefix = f"   {line_number}: "

                context.append(f"{line_prefix}{line_content}")

            # 构建结果
            result = {
                "文件名": os.path.basename(file_path),
                "关键词": keyword,
                "匹配总数": total_matches,
                "当前匹配索引": result_index,
                "当前匹配行号": match_line_index + 1,
                "总行数": len(lines),
                "上下文": "\n".join(context)
            }

            return result
        except Exception as e:
            return {"error": str(e)}

    async def write_text_file(self, file_path: str, content: str, start_line: int = -1) -> Dict[str, Any]:
        """
        将内容写入文本文件，支持插入、覆盖和追加

        Args:
            file_path: 目标文件路径
            content: 要写入的内容
            start_line: 开始写入的行号（1-based）。-1 表示追加，0 表示从头覆盖，正数表示插入

        Returns:
            包含操作结果的字典
        """
        is_valid, normalized_path, error_msg = self.validate_file_path(file_path)
        if not is_valid:
            return {"状态": "错误", "错误信息": error_msg}

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(normalized_path), exist_ok=True)

            # 追加模式
            if start_line == -1:
                async with aiofiles.open(normalized_path, "a", encoding="utf-8") as f:
                    await f.write(content + '\n')
                lines = []
                if os.path.exists(normalized_path):
                    async with aiofiles.open(normalized_path, "r", encoding="utf-8") as f:
                        lines = await f.readlines()
                return {
                    "状态": "成功",
                    "文件路径": normalized_path,
                    "追加行数": len(content.split('\n')),
                    "文件行数": len(lines)
                }

            # 从头覆盖模式
            if start_line == 0:
                async with aiofiles.open(normalized_path, "w", encoding="utf-8") as f:
                    await f.write(content + '\n')
                lines = []
                if os.path.exists(normalized_path):
                    async with aiofiles.open(normalized_path, "r", encoding="utf-8") as f:
                        lines = await f.readlines()
                return {
                    "状态": "成功",
                    "文件路径": normalized_path,
                    "覆盖行数": len(content.split('\n')),
                    "文件行数": len(lines)
                }

            # 插入模式
            if start_line > 0:
                lines = []
                if os.path.exists(normalized_path):
                    async with aiofiles.open(normalized_path, "r", encoding="utf-8") as f:
                        lines = await f.readlines()

                # 插入新内容
                index = start_line - 1
                # 在指定行号前插入，如果行号超出范围，则在末尾追加
                if index > len(lines):
                    index = len(lines)

                # 分割要插入的多行内容
                new_lines = [line + '\n' for line in content.split('\n')]

                lines[index:index] = new_lines

                async with aiofiles.open(normalized_path, "w", encoding="utf-8") as f:
                    await f.writelines(lines)

                return {
                    "状态": "成功",
                    "文件路径": normalized_path,
                    "插入行号": start_line,
                    "插入行数": len(new_lines),
                    "文件行数": len(lines)
                }

            return {"状态": "错误", "错误信息": f"无效的起始行号: {start_line}"}


        except Exception as e:
            return {"状态": "错误", "错误信息": str(e)}

    async def replace_file_lines(self, file_path: str, start_line: int, end_line: int, replacement_text: str) \
            -> Dict[str, Any]:
        """
        替换文件中的指定行范围

        Args:
            file_path: 要编辑的文件路径
            start_line: 开始替换的行号（从1开始计数，包含此行）
            end_line: 结束替换的行号（从1开始计数，不包含此行，左开右闭区间）
            replacement_text: 替换的文本内容

        Returns:
            包含替换结果的字典
        """
        is_valid, normalized_path, error_msg = self.validate_file_path(file_path)
        if not is_valid:
            return {"状态": "错误", "错误信息": error_msg}
        flag, lines = await self.judge_file_can_read(file_path)
        if not flag:
            return lines

        total_lines = len(lines)

        # 验证行号范围
        if start_line > total_lines:
            return {
                "状态": "错误",
                "错误信息": f"起始行号 {start_line} 超出文件总行数 {total_lines}"
            }

        # 调整end_line，确保不超出文件范围
        actual_end_line = min(end_line, total_lines + 1)

        # 转换为0基索引
        start_idx = start_line - 1
        end_idx = actual_end_line - 1

        # 处理替换文本，确保以换行符结尾（如果原来被替换的行有换行符）
        replacement_lines = []
        if replacement_text:
            # 分割替换文本为行
            replacement_lines = replacement_text.splitlines(True)  # 保留换行符
            # 如果最后一行没有换行符，且被替换的范围有内容，则添加换行符
            if replacement_lines and not replacement_lines[-1].endswith('\n') and end_idx > start_idx:
                replacement_lines[-1] += '\n'

        # 记录被替换的内容
        replaced_line_count = end_idx - start_idx

        # 执行替换
        new_lines = lines[:start_idx] + replacement_lines + lines[end_idx:]

        # 写回文件
        try:
            async with aiofiles.open(normalized_path, "w", encoding="utf-8") as f:
                await f.writelines(new_lines)
        except Exception as e:
            return {
                "状态": "错误",
                "错误信息": f"写入文件时出错: {str(e)}"
            }

        # 构建结果
        result = {
            "状态": "成功",
            "文件路径": file_path,
            "替换范围": f"第{start_line}行到第{actual_end_line - 1}行（左开右闭）",
            "原始行数": total_lines,
            "替换后行数": len(new_lines),
            "被替换的行数": replaced_line_count,
            "新增的行数": len(replacement_lines)
        }

        return result

    @classmethod
    def get_tool_by_name(cls, name: str, root_path: str) -> Optional[BaseTool]:
        """
        Get a specific tool by name.

        :param name: The name of the tool to retrieve.
        :param root_path: Path to the directory to list files from.
        :return: The tool if found, otherwise None.
        """
        obj = cls(root_path=root_path)
        if name == "list_files":
            return StructuredTool(
                name=f"{cls.list_files.__name__}",
                description=cls.list_files.__doc__,
                args_schema=FileDirToolInput,
                func=obj.list_files,
            )
        elif name == "get_file_details":
            return StructuredTool(
                name=f"{cls.get_file_details.__name__}",
                description=cls.get_file_details.__doc__,
                args_schema=FileToolInput,
                func=obj.get_file_details,
            )
        elif name == "search_files":
            return StructuredTool(
                name=f"{cls.search_files.__name__}",
                description=cls.search_files.__doc__,
                args_schema=SearchFilesInput,
                func=obj.search_files,
            )
        elif name == "read_text_file":
            return StructuredTool(
                name=f"{cls.read_text_file.__name__}",
                description=cls.read_text_file.__doc__,
                args_schema=ReadFileInput,
                coroutine=obj.read_text_file,
            )
        elif name == "search_text_in_file":
            return StructuredTool(
                name=f"{cls.search_text_in_file.__name__}",
                description=cls.search_text_in_file.__doc__,
                args_schema=SearchTextInput,
                coroutine=obj.search_text_in_file,
            )
        elif name == "write_text_file":
            return StructuredTool(
                name=f"{cls.write_text_file.__name__}",
                description=cls.write_text_file.__doc__,
                args_schema=WriteFileInput,
                coroutine=obj.write_text_file,
            )
        elif name == "replace_file_lines":
            return StructuredTool(
                name=f"{cls.replace_file_lines.__name__}",
                description=cls.replace_file_lines.__doc__,
                args_schema=ReplaceFileInput,
                coroutine=obj.replace_file_lines,
            )
        # 如果没有找到对应的工具，抛出异常
        raise Exception(f"LocalFile not found tool: {name}")
