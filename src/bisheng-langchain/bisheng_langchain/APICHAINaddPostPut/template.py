from langchain.prompts.prompt import PromptTemplate

API_URL_PROMPT_TEMPLATE = """You are given the below API Documentation:
{api_docs}
Using this documentation, generate the full API url to call for answering the user question.
You should build the API url in order to get a response that is as short as possible, while still getting the necessary information to answer the question. Pay attention to deliberately exclude any unnecessary pieces of data in the API call.
You should extract the request METHOD from doc, and generate the BODY data in JSON format according to the user question if necessary. The BODY data could be empty dict.

Question:{question}
"""

API_REQUEST_PROMPT_TEMPLATE = API_URL_PROMPT_TEMPLATE + """Output the API url, METHOD and BODY, join them with `|`. DO NOT GIVE ANY EXPLANATION."""

API_REQUEST_PROMPT = PromptTemplate(
    input_variables=[
        "api_docs",
        "question",
    ],
    template=API_REQUEST_PROMPT_TEMPLATE,
)

API_RESPONSE_PROMPT_TEMPLATE = (
    API_URL_PROMPT_TEMPLATE
    + """API url: {api_url}

Here is the response from the API:

{api_response}

Summarize this response to answer the original question.

Summary:"""
)

API_RESPONSE_PROMPT = PromptTemplate(
    input_variables=["api_docs", "question", "api_url", "api_response"],
    template=API_RESPONSE_PROMPT_TEMPLATE,
)