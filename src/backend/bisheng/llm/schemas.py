from typing import Optional, List

from pydantic import Field, BaseModel

from bisheng_langchain.linsight.const import TaskMode
from .domain.models import LLMModelBase, LLMServerBase


class LLMModelInfo(LLMModelBase):
    id: Optional[int] = None


class LLMServerInfo(LLMServerBase):
    id: Optional[int] = None
    models: List[LLMModelInfo] = Field(default_factory=list, description='模型列表')


class WSModel(BaseModel):
    key: Optional[str] = None
    id: str
    name: Optional[str] = None
    displayName: Optional[str] = None


class WorkbenchModelConfig(BaseModel):
    """
    灵思模型配置
    """
    # 任务执行模型
    task_model: Optional[WSModel] = Field(default=None, description='任务执行模型')
    # 检索embedding模型
    embedding_model: Optional[WSModel] = Field(default=None, description='embedding模型')
    # 灵思执行模式
    linsight_executor_mode: Optional[TaskMode] = Field(default=None, description='灵思执行模式')
    # 语音转文字模型
    asr_model: Optional[WSModel] = Field(default=None, description='语音转文字模型')
    tts_model: Optional[WSModel] = Field(default=None, description='文字转语音模型')


class LLMModelCreateReq(BaseModel):
    id: Optional[int] = Field(default=None, description='模型唯一ID, 更新时需要传')
    name: str = Field(..., description='模型展示名称')
    description: Optional[str] = Field(default='', description='模型描述')
    model_name: str = Field(..., description='模型名称')
    model_type: str = Field(..., description='模型类型')
    online: bool = Field(default=True, description='是否在线')
    config: Optional[dict] = Field(default=None, description='模型配置')


class LLMServerCreateReq(BaseModel):
    id: Optional[int] = Field(default=None, description='服务提供方ID, 更新时需要传')
    name: str = Field(..., description='服务提供方名称')
    description: Optional[str] = Field(default='', description='服务提供方描述')
    type: str = Field(..., description='服务提供方类型')
    limit_flag: Optional[bool] = Field(default=False, description='是否开启每日调用次数限制')
    limit: Optional[int] = Field(default=0, description='每日调用次数限制')
    config: Optional[dict] = Field(default=None, description='服务提供方配置')
    models: Optional[List[LLMModelCreateReq]] = Field(default_factory=list, description='服务提供方下的模型列表')


class KnowledgeLLMConfig(BaseModel):
    embedding_model_id: Optional[int] = Field(None, description='知识库默认embedding模型的ID')
    source_model_id: Optional[int] = Field(None, description='知识库溯源模型的ID')
    extract_title_model_id: Optional[int] = Field(None, description='文档知识库提取标题模型的ID')
    qa_similar_model_id: Optional[int] = Field(None, description='QA知识库相似问模型的ID')
    abstract_prompt: Optional[str] = Field(None, description='摘要提示词')


class AssistantLLMItem(BaseModel):
    model_id: Optional[int] = Field(None, description='模型的ID')
    agent_executor_type: Optional[str] = Field(default='ReAct',
                                               description='执行模式。function call 或者 ReAct')
    knowledge_max_content: Optional[int] = Field(default=15000, description='知识库检索最大字符串数')
    knowledge_sort_index: Optional[bool] = Field(default=False, description='知识库检索后是否重排')
    streaming: Optional[bool] = Field(default=True, description='是否开启流式')
    default: Optional[bool] = Field(default=False, description='是否为默认模型')


class AssistantLLMConfig(BaseModel):
    llm_list: Optional[List[AssistantLLMItem]] = Field(default_factory=list, description='助手可选的LLM列表')
    auto_llm: Optional[AssistantLLMItem] = Field(None, description='助手画像自动优化模型的配置')


class EvaluationLLMConfig(BaseModel):
    model_id: Optional[int] = Field(None, description='评测功能默认模型的ID')
