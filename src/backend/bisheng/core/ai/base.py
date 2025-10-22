import tempfile
from abc import ABC, abstractmethod
from typing import Optional, Union, BinaryIO, Sequence

from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import ConfigDict


class BaseASRClient(ABC):
    """ASR (Automatic Speech Recognition) 基础接口类"""

    async def transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: Optional[str] = None,
            model: Optional[str] = None,
            **kwargs
    ) -> str:
        """
        将音频转换为文本

        Args:
            audio: 音频文件路径、音频字节数据或文件对象
            language: 语言代码，如 'zh', 'en'
            model: 使用的模型名称

        Returns:
            转录的文本内容
        """
        if not audio:
            raise ValueError("Audio input is required")

        if isinstance(audio, str):
            with open(audio, 'rb') as audio_file:
                audio_bytes = audio_file.read()
        elif isinstance(audio, bytes):
            audio_bytes = audio
        elif hasattr(audio, 'read'):
            audio_bytes = audio.read()
        else:
            raise ValueError("Invalid audio input type")

        with tempfile.NamedTemporaryFile(delete=True, suffix=".wav") as f:
            f.write(audio_bytes)
            f.flush()
            return await self._transcribe(f.name, language=language, model=model, **kwargs)

    @abstractmethod
    async def _transcribe(self, audio: str, language: Optional[str] = None, model: Optional[str] = None,
                          **kwargs) -> str:
        """
        内部方法：将音频转换为文本

        Args:
            audio: 音频文件路径, 处理完成后会自动删除文件
            language: 语言代码，如 'zh', 'en'
            model: 使用的模型名称

        Returns:
            转录的文本内容
        """
        raise NotImplementedError


class BaseTTSClient(ABC):
    """TTS (Text To Speech) 基础接口类"""

    @abstractmethod
    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: str = "mp3"
    ) -> bytes:
        """
        将文本合成为语音

        Args:
            text: 要合成的文本
            voice: 声音选项
            language: 语言代码
            format: 音频格式，如 'mp3', 'wav'

        Returns:
            音频字节数据
        """
        pass


class BaseRerank(BaseDocumentCompressor):
    """Rerank base interface class"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    def compress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        """Compress retrieved documents given the query context.

        Args:
            documents: The retrieved documents.
            query: The query context.
            callbacks: Optional callbacks to run during compression.

        Returns:
            The compressed documents.

        """

    @staticmethod
    def sort_rerank_result(documents: Sequence[Document], results: list[dict]) -> Sequence[Document]:
        """Sort and annotate original documents based on rerank results."""
        sorted_docs = []
        for res in results:
            index = res.get("index")
            if index is not None and 0 <= index < len(documents):
                doc = documents[index]
                doc.metadata["relevance_score"] = res.get("relevance_score")
                sorted_docs.append(doc)
        return sorted_docs
