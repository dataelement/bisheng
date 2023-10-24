import autogen

config_list = autogen.config_list_from_json("OAI_CONFIG_LIST")

# create an AssistantAgent instance named "assistant"
assistant = autogen.AssistantAgent(
    name="assistant",
    llm_config={
        "seed": 41,
        "config_list": config_list,
    }
)
# create a UserProxyAgent instance named "user_proxy"
user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    human_input_mode="ALWAYS",
    is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
)

# the purpose of the following line is to log the conversation history
autogen.ChatCompletion.start_logging()
