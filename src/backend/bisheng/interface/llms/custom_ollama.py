from typing import Iterator, Optional, Any, List, AsyncIterator
from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, AIMessageChunk
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field
from loguru import logger


class CustomChatOllamaWithReasoning(ChatOllama):
    """
    Custom class inheriting from ChatOllama that supports processing reasoning content in <think> tags.
    
    During streaming output:
    - Content outside <think> tags: content has value, reasoning_content is null
    - Content inside <think> tags: reasoning_content has value, content is null
    - <think> and </think> tags themselves are not returned
    """
    
    in_think: bool = Field(default=False, description="Track whether inside think tags")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs) -> Any:
        """Handle non-streaming calls, extract think content to reasoning_content field"""
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        if result.generations and len(result.generations) > 0:
            for generation in result.generations:
                if hasattr(generation, 'message') and hasattr(generation.message, 'content'):
                    original_content = generation.message.content
                    reasoning_content, cleaned_content = self._extract_think_content(original_content)
                    
                    # Set the cleaned content
                    generation.message.content = cleaned_content
                    
                    # Add reasoning_content to additional_kwargs
                    if not hasattr(generation.message, 'additional_kwargs'):
                        generation.message.additional_kwargs = {}
                    generation.message.additional_kwargs['reasoning_content'] = reasoning_content if reasoning_content else None
                    
                    logger.debug(f"Original content length: {len(original_content)}, reasoning length: {len(reasoning_content)}, processed length: {len(cleaned_content)}")
                
                if hasattr(generation, 'text'):
                    reasoning_content, cleaned_text = self._extract_think_content(generation.text)
                    generation.text = cleaned_text
                    logger.debug(f"Original text length: {len(generation.text)}, processed length: {len(cleaned_text)}")
        return result

    async def _agenerate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Optional[AsyncCallbackManagerForLLMRun] = None, **kwargs) -> ChatResult:
        """Handle async non-streaming calls, extract think content to reasoning_content field"""
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        if result.generations and len(result.generations) > 0:
            for generation in result.generations:
                if hasattr(generation, 'message') and hasattr(generation.message, 'content'):
                    original_content = generation.message.content
                    reasoning_content, cleaned_content = self._extract_think_content(original_content)
                    
                    # Set the cleaned content
                    generation.message.content = cleaned_content
                    
                    # Add reasoning_content to additional_kwargs
                    if not hasattr(generation.message, 'additional_kwargs'):
                        generation.message.additional_kwargs = {}
                    generation.message.additional_kwargs['reasoning_content'] = reasoning_content if reasoning_content else None
                    
                    logger.debug(f"Async original content length: {len(original_content)}, reasoning length: {len(reasoning_content)}, processed length: {len(cleaned_content)}")
                
                if hasattr(generation, 'text'):
                    reasoning_content, cleaned_text = self._extract_think_content(generation.text)
                    generation.text = cleaned_text
                    logger.debug(f"Async original text length: {len(generation.text)}, processed length: {len(cleaned_text)}")
        return result
    
    def _extract_think_content(self, content: str) -> tuple[str, str]:
        """Extract think tag content, return (reasoning_content, cleaned_content)"""
        import re
        
        # Extract content inside think tags
        think_pattern = r'<think>(.*?)</think>'
        think_matches = re.findall(think_pattern, content, flags=re.DOTALL)
        reasoning_content = '\n'.join(think_matches).strip() if think_matches else ''
        
        # Remove entire <think>...</think> blocks
        cleaned_content = re.sub(r'<think>.*?</think>\s*', '', content, flags=re.DOTALL).strip()
        
        return reasoning_content, cleaned_content

    def _remove_think_tags(self, content: str) -> str:
        """移除think标签，只保留标签外的内容"""
        _, cleaned_content = self._extract_think_content(content)
        return cleaned_content

    def _stream(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs) -> Iterator[ChatGenerationChunk]:
        """
        处理流式输出，直接修改原始chunk添加reasoning_content字段
        
        Args:
            messages: 输入消息列表
            stop: 停止词列表
            run_manager: 回调管理器
            **kwargs: 其他参数
            
        Yields:
            ChatGenerationChunk: 修改后的chunk，包含content和reasoning_content字段
        """
        logger.error("=== CustomChatOllamaWithReasoning._stream被调用 ===")
        print("=== CustomChatOllamaWithReasoning._stream被调用 ===", flush=True)
        # 重置think状态
        self.in_think = False
        
        try:
            # 调用父类的_stream方法获取原始chunk
            for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                if hasattr(chunk, 'message') and hasattr(chunk.message, 'content'):
                    content = chunk.message.content or ""
                    
                    # 添加调试信息
                    logger.debug(f"处理chunk内容: '{content}', in_think状态: {self.in_think}")
                    
                    if not content:
                        # 添加reasoning_content字段并设为null
                        if not hasattr(chunk.message, 'additional_kwargs'):
                            chunk.message.additional_kwargs = {}
                        chunk.message.additional_kwargs['reasoning_content'] = None
                        yield chunk
                        continue
                    
                    # 处理content中的think标签，返回修改后的chunk列表
                    modified_chunks = self._process_chunk_with_think_tags(chunk, content)
                    
                    # 输出处理后的chunk
                    if modified_chunks:
                        for modified_chunk in modified_chunks:
                            yield modified_chunk
                    # 如果modified_chunks为空，说明这个chunk完全被跳过（如只包含标签）
                else:
                    # 没有content的chunk，添加reasoning_content字段并设为null
                    if hasattr(chunk, 'message') and chunk.message:
                        if not hasattr(chunk.message, 'additional_kwargs'):
                            chunk.message.additional_kwargs = {}
                        chunk.message.additional_kwargs['reasoning_content'] = None
                    yield chunk
                            
        except Exception as e:
            logger.error(f"CustomChatOllamaWithReasoning处理出错: {e}")
            raise e

    def _process_chunk_with_think_tags(self, original_chunk, content: str) -> List[ChatGenerationChunk]:
        """
        处理包含think标签的chunk，返回修改后的chunk列表
        
        Args:
            original_chunk: 原始chunk
            content: chunk的文本内容
            
        Returns:
            List[ChatGenerationChunk]: 修改后的chunk列表
        """
        chunks = []
        current_pos = 0
        
        while current_pos < len(content):
            if not self.in_think:
                # 不在think标签内，查找<think>标签
                think_start = content.find("<think>", current_pos)
                if think_start != -1:
                    # 找到<think>标签，输出标签前的普通内容
                    before_think = content[current_pos:think_start]
                    if before_think:
                        # 创建普通内容的chunk
                        new_chunk = ChatGenerationChunk(
                            message=AIMessageChunk(
                                content=before_think,
                                additional_kwargs={'reasoning_content': None}
                            ),
                            generation_info=original_chunk.generation_info
                        )
                        chunks.append(new_chunk)
                    
                    # 进入think状态，跳过<think>标签和可能的换行符
                    current_pos = think_start + 7  # len("<think>")
                    # 如果<think>后紧跟换行符，也跳过
                    if current_pos < len(content) and content[current_pos] == '\n':
                        current_pos += 1
                    self.in_think = True
                    # 重要：如果这个chunk只包含<think>标签，不输出任何内容
                    if think_start == 0 and current_pos >= len(content):
                        break
                else:
                    # 没有找到<think>标签，输出剩余的普通内容
                    remaining = content[current_pos:]
                    if remaining:
                        new_chunk = ChatGenerationChunk(
                            message=AIMessageChunk(
                                content=remaining,
                                additional_kwargs={'reasoning_content': None}
                            ),
                            generation_info=original_chunk.generation_info
                        )
                        chunks.append(new_chunk)
                    break
            else:
                # 在think标签内，查找</think>标签
                think_end = content.find("</think>", current_pos)
                if think_end != -1:
                    # 找到</think>标签，输出推理内容
                    reasoning = content[current_pos:think_end]
                    if reasoning:
                        # 创建推理内容的chunk：content为null，reasoning_content有值
                        new_chunk = ChatGenerationChunk(
                            message=AIMessageChunk(
                                content="",
                                additional_kwargs={'reasoning_content': reasoning}
                            ),
                            generation_info=original_chunk.generation_info
                        )
                        chunks.append(new_chunk)
                    
                    # 退出think状态，跳过</think>标签和可能的换行符
                    current_pos = think_end + 8  # len("</think>")
                    # 如果</think>后紧跟换行符，也跳过
                    if current_pos < len(content) and content[current_pos] == '\n':
                        current_pos += 1
                    self.in_think = False
                else:
                    # 没有找到</think>标签，输出剩余的推理内容
                    remaining_reasoning = content[current_pos:]
                    if remaining_reasoning:
                        new_chunk = ChatGenerationChunk(
                            message=AIMessageChunk(
                                content="",
                                additional_kwargs={'reasoning_content': remaining_reasoning}
                            ),
                            generation_info=original_chunk.generation_info
                        )
                        chunks.append(new_chunk)
                    break
                    
        return chunks 

    async def _astream(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Optional[AsyncCallbackManagerForLLMRun] = None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        """
        处理异步流式输出，直接修改原始chunk添加reasoning_content字段
        
        Args:
            messages: 输入消息列表
            stop: 停止词列表
            run_manager: 异步回调管理器
            **kwargs: 其他参数
            
        Yields:
            ChatGenerationChunk: 修改后的chunk，包含content和reasoning_content字段
        """
        logger.error("=== CustomChatOllamaWithReasoning._astream被调用 ===")
        print("=== CustomChatOllamaWithReasoning._astream被调用 ===", flush=True)
        # 重置think状态
        self.in_think = False
        
        try:
            # 调用父类的_astream方法获取原始chunk
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                if hasattr(chunk, 'message') and hasattr(chunk.message, 'content'):
                    content = chunk.message.content or ""
                    
                    # 添加调试信息
                    logger.debug(f"异步处理chunk内容: '{content}', in_think状态: {self.in_think}")
                    
                    if not content:
                        # 添加reasoning_content字段并设为null
                        if not hasattr(chunk.message, 'additional_kwargs'):
                            chunk.message.additional_kwargs = {}
                        chunk.message.additional_kwargs['reasoning_content'] = None
                        yield chunk
                        continue
                    
                    # 处理content中的think标签，返回修改后的chunk列表
                    modified_chunks = self._process_chunk_with_think_tags(chunk, content)
                    
                    # 输出处理后的chunk
                    if modified_chunks:
                        for modified_chunk in modified_chunks:
                            yield modified_chunk
                    # 如果modified_chunks为空，说明这个chunk完全被跳过（如只包含标签）
                else:
                    # 没有content的chunk，添加reasoning_content字段并设为null
                    if hasattr(chunk, 'message') and chunk.message:
                        if not hasattr(chunk.message, 'additional_kwargs'):
                            chunk.message.additional_kwargs = {}
                        chunk.message.additional_kwargs['reasoning_content'] = None
                    yield chunk
                            
        except Exception as e:
            logger.error(f"CustomChatOllamaWithReasoning异步流式处理出错: {e}")
            raise e