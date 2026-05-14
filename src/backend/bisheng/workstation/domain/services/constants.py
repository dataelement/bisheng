TITLE_INSTRUCTION = (
    'a concise, 5-word-or-less title for the conversation, using its same language, '
    'with no punctuation. Apply title case conventions appropriate for the language. '
    'Never directly mention the language name or the word "title"'
)

PROMPT_SEARCH = (
    '用户的问题是：%s '
    '判断用户的问题是否需要联网搜索，如果需要返回数字1，如果不需要返回数字0。只返回1或0，不要返回其他信息。'
    '如果问题涉及到实时信息、最新事件或特定数据库查询等超出你知识截止日期（2024年7月）的内容，就需要进行联网搜索来获取最新信息。'
)

VISUAL_MODEL_FILE_TYPES = ['png', 'jpg', 'jpeg', 'webp', 'gif']
USED_APP_PIN_TYPE = 'used_app_pin'
