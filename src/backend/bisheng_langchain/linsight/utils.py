import json
import os
import re
import uuid
from typing import Any

from langchain_core.language_models import BaseLanguageModel
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(os.path.join(os.path.dirname(__file__), "resource/model_tokenizer"),
                                          trust_remote_code=True)


def extract_json_from_markdown(markdown_code_block: str) -> dict:
    """
    从markdown代码块中提取JSON内容。
    :param markdown_code_block: 包含JSON的markdown代码块字符串。
    :return: 提取的JSON对象，如果没有找到则抛出异常。
    """
    # 定义正则表达式模式
    json_pattern = r"```json\n(.*?)\n```"
    # 使用 re.DOTALL 使 . 能够匹配换行符
    matches = re.search(json_pattern, markdown_code_block, re.DOTALL)

    if not matches:
        try:
            # 尝试直接解析整个markdown代码块为JSON
            return json.loads(markdown_code_block)
        except json.decoder.JSONDecodeError:
            raise Exception(f"Invalid JSON format from response: {markdown_code_block}")

    json_str = matches.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        raise Exception(f"Invalid JSON format from json_str: {json_str}")


# 提取文本中的markdown代码块内容
def extract_code_blocks(markdown_code_block: str) -> str | None:
    # 定义正则表达式模式
    pattern = r"```\w*\s*(.*?)```"

    # 使用 re.DOTALL 使 . 能够匹配换行符
    matches = re.findall(pattern, markdown_code_block, re.DOTALL)

    if not matches:
        return None
    res = ""
    for match in matches:
        res += f"{match.strip()}\n"
    # 去除每段代码块两端的空白字符
    return res


def format_size(size_bytes):
    """将字节大小格式化为人类可读形式"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def encode_str_tokens(text: str) -> list[int]:
    """
    Encode a string into a list of token IDs using the BERT tokenizer.
    :param text: The input string to be encoded.
    :return: A list of token IDs.
    """
    tokens = tokenizer.encode(text)
    return tokens


def generate_uuid_str() -> str:
    """
    Generate a UUID string.
    :return: A UUID string.
    """
    return uuid.uuid4().hex


def record_llm_prompt(llm: BaseLanguageModel, prompt: str, answer: str, token_usage: Any, cost_time: float,
                      debug_id: str):
    if not debug_id:
        return

    generate_tokens_num = 0
    prompt_tokens_num = 0
    cached_tokens_num = 0
    try:
        token_usage = token_usage.response_metadata.get('token_usage', {}) or token_usage.usage_metadata

        if token_usage:
            generate_tokens_num = token_usage.get('output_tokens', 0) or token_usage.get('completion_tokens', 0)
            prompt_tokens_num = token_usage.get('input_tokens', 0) or token_usage.get('prompt_tokens', 0)
            cached_tokens_num = token_usage.get('cached_tokens', 0) or token_usage.get('prompt_tokens_details', {}).get(
                'cached_tokens', 0) or token_usage.get('input_tokens_details', {}).get('cache_read', 0)
    except Exception:
        pass
    try:
        model_name = getattr(llm, "model")
    except AttributeError:
        try:
            model_name = getattr(llm, "model_name") or getattr(llm, "deployment_name", "unknown_model")
        except AttributeError:
            model_name = "unknown_model"

    debug_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "linsightdebug"))
    os.makedirs(debug_path, exist_ok=True)
    file_path = os.path.join(debug_path, f"{debug_id}.jsonl")
    with open(f'{file_path}', 'a') as f:
        f.write(
            json.dumps({
                "model": model_name,
                "prompt": prompt,
                "response": answer,
                "generate_tokens_num": generate_tokens_num,
                "prompt_tokens_num": prompt_tokens_num,
                "cached_tokens_num": cached_tokens_num,
                "time": cost_time
            }, ensure_ascii=False) + "\n"
        )
