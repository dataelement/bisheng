from bisheng_langchain.gpts.prompts.assistant_prompt_opt import ASSISTANT_PROMPT_OPT
from bisheng_langchain.gpts.prompts.assistant_prompt_base import ASSISTANT_PROMPT_DEFAULT
from bisheng_langchain.gpts.prompts.assistant_prompt_cohere import ASSISTANT_PROMPT_COHERE
from bisheng_langchain.gpts.prompts.breif_description_prompt import BREIF_DES_PROMPT
from bisheng_langchain.gpts.prompts.opening_dialog_prompt import OPENDIALOG_PROMPT
from bisheng_langchain.gpts.prompts.select_tools_prompt import HUMAN_MSG, SYS_MSG


__all__ = [
    "ASSISTANT_PROMPT_DEFAULT",
    "ASSISTANT_PROMPT_COHERE",
    "ASSISTANT_PROMPT_OPT",
    "OPENDIALOG_PROMPT",
    "BREIF_DES_PROMPT",
    "SYS_MSG",
    "HUMAN_MSG",
]
