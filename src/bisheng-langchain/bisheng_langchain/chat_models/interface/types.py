# from typing import Union

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class Function(BaseModel):
    name: str
    description: str
    parameters: dict


class ChatInput(BaseModel):
    model: str
    messages: list[Message] = []
    top_p: float = None
    temperature: float = None
    n: int = 1
    stream: bool = False
    stop: str = None
    max_tokens: int = 256
    functions: list[Function] = []
    function_call: str = None


class Choice(BaseModel):
    index: int
    message: Message = None
    finish_reason: str = 'stop'


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatOutput(BaseModel):
    status_code: int
    status_message: str = 'success'
    id: str = None
    object: str = None
    model: str = None
    created: int = None
    choices: list[Choice] = []
    usage: Usage = None


class CompletionsInput(BaseModel):
    model: str
    prompt: str
    top_p: float = None
    temperature: float = None
    n: int = 1
    stream: bool = True
    stop: str = None
    max_tokens: int = 256
