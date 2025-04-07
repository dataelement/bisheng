{
    "sidebarIcon": {
        "enabled": true,
        "image": "/bisheng/icon/db6b1fc4969e4f90badde06b51d905c8.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20250403%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250403T135540Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=8c28823d17f1771b48ea368515bda034c47549738b12ddaf367a583b7e2c855d"
    },
    "assistantIcon": {
        "enabled": true,
        "image": "/bisheng/icon/66cb84ee946344369a2d5d93943ddbae.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20250403%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250403T135559Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=51445b15b5fb8e8314a058864cdd16fefab1fddf87b585028cae7276d6f74327"
    },
    "sidebarSlogan": "Deepseek",
    "welcomeMessage": "我是 DeepSeek，很高兴见到你！",
    "functionDescription": "我可以帮你写代码、读文件、写作各种创意内容，请把你的任务交给我吧～",
    "inputPlaceholder": "使用默认“给Deepseek发送消息",
    "models": [
        {
            "key": "88ae",
            "id": 26,
            "name": "",
            "displayName": "chatgpt"
        },
        {
            "key": "777f",
            "id": 25,
            "name": "",
            "displayName": "deepseek"
        }
    ],
    "voiceInput": {
        "enabled": false,
        "model": ""
    },
    "webSearch": {
        "enabled": true,
        "tool": "bing",
        "bingKey": "",
        "bingUrl": "https://api.bing.microsoft.com/v7.0/search",
        "prompt": "# 以下内容是基于用户发送的消息的搜索结果:\n{search_results}\n在我给你的搜索结果中，每个结果都是[webpage X begin]...[webpage X end]格式的，X代表每篇文章的数字索引。请在适当的情况下在句子末尾引用上下文。请按照引用编号[citation:X]的格式在答案中对应部分引用上下文。如果一句话源自多个上下文，请列出所有相关的引用编号，例如[citation:3][citation:5]，切记不要将引用集中在最后返回引用编号，而是在答案对应部分列出。\n在回答时，请注意以下几点：\n- 今天是{cur_date}。\n- 并非搜索结果的所有内容都与用户的问题密切相关，你需要结合问题，对搜索结果进行甄别、筛选。\n- 对于列举类的问题（如列举所有航班信息），尽量将答案控制在10个要点以内，并告诉用户可以查看搜索来源、获得完整信息。优先提供信息完整、最相关的列举项；如非必要，不要主动告诉用户搜索结果未提供的内容。\n- 对于创作类的问题（如写论文），请务必在正文的段落中引用对应的参考编号，例如[citation:3][citation:5]，不能只在文章末尾引用。你需要解读并概括用户的题目要求，选择合适的格式，充分利用搜索结果并抽取重要信息，生成符合用户要求、极具思想深度、富有创造力与专业性的答案。你的创作篇幅需要尽可能延长，对于每一个要点的论述要推测用户的意图，给出尽可能多角度的回答要点，且务必信息量大、论述详尽。\n- 如果回答很长，请尽量结构化、分段落总结。如果需要分点作答，尽量控制在5个点以内，并合并相关的内容。\n- 对于客观类的问答，如果问题的答案非常简短，可以适当补充一到两句相关信息，以丰富内容。\n- 你需要根据用户要求和回答内容选择合适、美观的回答格式，确保可读性强。\n- 你的回答应该综合多个相关网页来回答，不能重复引用一个网页。\n- 除非用户要求，否则你回答的语言需要和用户提问的语言保持一致。\n\n# 用户消息为：\n{question}"
    },
    "knowledgeBase": {
        "enabled": true,
        "prompt": ""
    },
    "fileUpload": {
        "enabled": true,
        "prompt": "[file name]: {file_name}\n..."
    }
}