BASE_SYSTEM_MESSAGE = "你是一名专业的信息提取助手。你的目标是从提供的原文中，根据指定的“关键词”提取相关信息，并以JSON格式输出。如果原文中没有相关关键词的信息，则在JSON对象中相应键的位置上输出空列表。记住，一定不要在输出的json中添加“关键词”中没有的词。\n"
BASE_USER_MESSAGE = """原文：

{context}

关键词：
{keywords}

输出格式：
```json
{{
    "key1": ["value1"],
    "key2": ["value2", "value3"],
    "key3": []
}}
```
"""

EXAMPLE_FORMAT = """原文：

{context}

关键词：
{keywords}

抽取结果：
"""

FEW_SHOT_SYSTEM_MESSAGE = """你是一名专业的信息提取助手。你的目标是从提供的原文中，根据指定的“关键词”提取相关信息，并以JSON格式输出。\
如果原文中没有相关关键词的信息，则在JSON对象中相应键的位置上输出空列表。\
记住，一定不要在输出的json中添加“关键词”中没有的词。

示例

{examples}
"""
FEW_SHOT_USER_MESSAGE = """原文：

{context}

关键词：
{keywords}

提取结果：
"""
