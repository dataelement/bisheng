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
    json_pattern = r"```json(.*?)```"
    # 使用 re.DOTALL 使 . 能够匹配换行符
    matches = re.search(json_pattern, markdown_code_block, re.DOTALL)

    if not matches:
        try:
            # 尝试直接解析整个markdown代码块为JSON
            return json.loads(markdown_code_block)
        except json.decoder.JSONDecodeError:
            raise Exception(f"Invalid JSON format from llm response")

    json_str = matches.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        raise Exception(f"Invalid JSON format from json str")


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


def get_model_name_from_llm(llm: BaseLanguageModel) -> str:
    """
    Get the model name from a BaseLanguageModel instance.
    :param llm: An instance of BaseLanguageModel.
    :return: The model name as a string. If the model name cannot be determined, returns "unknown_model".
    """
    try:
        model_name = getattr(llm, "model")
    except AttributeError:
        try:
            model_name = getattr(llm, "model_name") or getattr(llm, "deployment_name")
        except AttributeError:
            model_name = "unknown_model"
    return model_name


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

    model_name = get_model_name_from_llm(llm)

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


if __name__ == '__main__':
    a = {
        "totalResponseMessage": "```json\n{\n \"total_thought\": \"本任务需系统性盘点2025年企业AI产品，最终输出结构化Markdown表格文件。根据指导手册，需分为六大步骤：1）确定信息源网站清单，2）明确表格结构与输出文件名，3）收集产品名称清单，4）收集并写入产品详细信息（每个产品为子步骤），5）格式检查，6）交付与汇报。每步均有明确目标、依赖关系和工具要求，需严格按SOP执行，确保信息真实、格式规范、内容完整。\",\n \"steps\": [\n {\n \"thought\": \"第一步需确定权威且更新及时的2025年企业AI产品信息源网站清单，为后续检索产品信息做准备。需使用网页搜索工具，筛选出至少3-5个全球知名、专门收录企业AI新品的网站，并整理名称与链接。此步骤不依赖前序步骤，结果将供后续定向检索使用。\",\n \"step_id\": \"step_1\",\n \"profile\": \"确定2025年企业AI产品信息源网站清单。\",\n \"target\": \"输出包含网站名称和链接的清单，至少3-5个权威信息源。\",\n \"workflow\": \"使用@fire_search_scrape@和@tool_type_17_06a943c59f33a34bb5924aaf72cd2995@，以“2025企业AI产品发布网站”、“2025企业AI新品收录平台”、“2025企业AI工具导航网站”、“2025年企业AI产品盘点”等关键词，检索全球范围内专门收录和发布2025年企业AI产品的网站。筛选出权威且更新及时的网站（如Product Hunt、AI Top Tools、Gartner、Forrester、TechCrunch等），整理名称和链接，形成信息源清单。\",\n \"precautions\": \"优先选择全球知名、更新及时的网站，确保信息源权威可靠。\",\n \"input_thought\": \"本步骤为起始步骤，无需依赖前置步骤，仅需用户原始问题作为输入。\",\n \"input\": [\"query\"],\n \"node_loop\": false },\n {\n \"thought\": \"第二步需明确汇总内容结构和输出文件名，为后续数据收集和写入做格式准备。需确定表格字段（产品名称、简介、发布时间、官网链接、主要功能/亮点、适用行业/场景），并在指定文件写入表头和概览说明。依赖于步骤1的信息源清单，确保表格结构与SOP一致。\",\n \"step_id\": \"step_2\",\n \"profile\": \"明确表格字段清单与输出文件名，写入表头和概览说明。\",\n \"target\": \"输出表格字段清单，创建2025企业AI产品汇总.md文件并写入表头和说明。\",\n \"workflow\": \"确定表格字段：产品名称、简介、发布时间、官网链接、主要功能/亮点、适用行业/场景。确定输出文件名为2025企业AI产品汇总.md。使用@add_text_to_file@工具，在文件中写入盘点概览说明及Markdown表头：| 产品名称 | 简介 | 发布时间 | 官网链接 |主要功能/亮点 |适用行业/场景 |，表头后不留空行。\",\n \"precautions\": \"表头后不要有空行，字段需覆盖所有要求内容。\",\n \"input_thought\": \"需依赖步骤1的信息源清单作为后续检索参考，但本步骤主要为格式准备，输入为step_1。\",\n \"input\": [\"step_1\"],\n \"node_loop\": false },\n {\n \"thought\": \"第三步需收集不少于20款2025年已发布或计划发布的企业AI产品名称。需依次检索步骤1确定的信息源网站，验证每个产品的首次发布时间为2025年，必要时补充知识库检索。此步骤依赖于step_1（信息源清单），结果为产品名称清单。\",\n \"step_id\": \"step_3\",\n \"profile\": \"收集2025年企业AI产品名称清单，确保数量和发布时间要求。\",\n \"target\": \"输出不少于20款2025年企业AI产品名称清单。\",\n \"workflow\": \"依次检索step_1确定的信息源网站，查找2025年已发布或计划发布的企业AI产品。每找到一个产品名称，使用@web_search@或@tool_type_17_06a943c59f33a34bb5924aaf72cd2995@工具，验证其首次发布日期为2025年（已发布或官方明确计划2025年发布），不符合则剔除。如信息不足，补充检索知识库id=287。重复以上步骤，直至找到不少于20款产品，若超过则随机挑选20条。\",\n \"precautions\": \"必须验证每个产品的首次发布时间，确保为2025年已发布或计划发布。\",\n \"input_thought\": \"需依赖step_1（信息源清单），作为检索目标；部分信息可参考step_2（表格结构），但主要依赖step_1。\",\n \"input\": [\"step_1\"],\n \"node_loop\": false },\n {\n \"thought\": \"第四步需针对每个产品收集详细信息并写入文件。每个产品为一个子步骤，需搜索官网或权威介绍，提取所有表格字段内容，并使用@add_text_to_file@工具逐条追加写入2025企业AI产品汇总.md。此步骤依赖于step_2（表格结构与文件名）和step_3（产品名称清单），需确保每条信息真实可靠、格式规范。\",\n \"step_id\": \"step_4\",\n \"profile\": \"收集每个产品的详细信息并写入Markdown表格，每个产品为一个子步骤。\",\n \"target\": \"2025企业AI产品汇总.md文件完整内容，每个产品信息均已写入。\",\n \"workflow\": \"对于step_3中的每个产品名称，使用@fire_search_scrape@、@fire_search_crawl@、@tool_type_17_06a943c59f33a34bb5924aaf72cd2995@工具，搜索官网或权威介绍，提取产品名称、简介、发布时间（需核查为2025年）、官网链接、主要功能/亮点、适用行业/场景。整理为Markdown表格行，格式如：| xxx | xxx |2025-03-15 | https://xxx.com | xxx | xxx |。每收集到一个产品信息，立即使用@add_text_to_file@追加写入2025企业AI产品汇总.md文件。\",\n \"precautions\": \"信息需真实可靠，优先引用官网和权威评价。每收集到一个产品，立即追加写入文件，避免内容丢失。\",\n \"input_thought\": \"需依赖step_2（表格结构与文件名）和step_3（产品名称清单），每个产品为一个子步骤，需循环处理。\",\n \"input\": [\"step_2\", \"step_3\"],\n \"node_loop\": true },\n {\n \"thought\": \"第五步需检查文件格式是否正确，确保表格严格符合Markdown规范，无空行。需使用@read_text_file@工具读取文件内容，若发现格式问题则用@add_text_to_file@或@replace_file_lines@工具修正。此步骤依赖于step_4（已写入完整内容的文件）。\",\n \"step_id\": \"step_5\",\n \"profile\": \"检查2025企业AI产品汇总.md文件格式，确保表格规范。\",\n \"target\": \"输出格式正确的2025企业AI产品汇总.md文件。\",\n \"workflow\": \"使用@read_text_file@工具读取2025企业AI产品汇总.md内容，检查表格是否严格符合Markdown规范，表格内不应出现空行。若发现不规范，使用@add_text_to_file@或@replace_file_lines@工具修正整理后的内容，重新写入文件。\",\n \"precautions\": \"表格内不应出现空行，需严格符合Markdown规范。\",\n \"input_thought\": \"需依赖step_4（已写入完整内容的文件）。\",\n \"input\": [\"step_4\"],\n \"node_loop\": false },\n {\n \"thought\": \"第六步为交付与汇报，需输出2025企业AI产品汇总.md文件的具体地址，并简要说明文件结构和内容组成，便于查阅和后续引用。此步骤依赖于step_5（格式检查后的文件）。\",\n \"step_id\": \"step_6\",\n \"profile\": \"交付最终结果文件，说明文件结构和内容。\",\n \"target\": \"输出2025企业AI产品汇总.md文件地址及结构说明。\",\n \"workflow\": \"交付2025企业AI产品汇总.md的具体地址，并简要说明文件结构和内容组成，包括表格字段和数据来源，便于用户查阅和引用。\",\n \"precautions\": \"无特殊注意事项。\",\n \"input_thought\": \"需依赖step_5（格式检查后的文件）。\",\n \"input\": [\"step_5\"],\n \"node_loop\": false }\n ]\n}\n```",
        "sseId": "chatcmpl-Cs1oYqfeOddC9UHSGa6KLWiahZlF3"}
    extract_json_from_markdown(a["totalResponseMessage"])
