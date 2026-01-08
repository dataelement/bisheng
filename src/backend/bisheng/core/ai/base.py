import asyncio
import os
import tempfile
import uuid
from abc import ABC, abstractmethod
from typing import Optional, Union, BinaryIO, Sequence

import aiofiles
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import ConfigDict


class BaseASRClient(ABC):
    """ASR (Automatic Speech Recognition) Base Interface Class"""

    async def transcribe(
            self,
            audio: Union[str, bytes, BinaryIO],
            language: Optional[str] = None,
            model: Optional[str] = None,
            **kwargs
    ) -> str:
        """
        Convert Audio to Text

        Args:
            audio: Audio file path, audio byte data, or file object
            language: Language code, e.g. 'zh', 'en'
            model: Used Model Name

        Returns:
            Transcribed text content
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
        tmp_dir = tempfile.gettempdir()

        tmp_file_path = os.path.join(tmp_dir, uuid.uuid4().hex + '.wav')
        # ffmpeg Convert To16kSampling Rate MonowavDoc.
        converted_file_path = os.path.join(tmp_dir, uuid.uuid4().hex + '_16k_mono.wav')

        try:
            async with aiofiles.open(tmp_file_path, 'wb') as f:
                await f.write(audio_bytes)

            command = f'ffmpeg -y -i "{tmp_file_path}" -ar 16000 -ac 1 "{converted_file_path}"'
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await process.communicate()

            return await self._transcribe(converted_file_path, language=language, model=model, **kwargs)
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
            if os.path.exists(converted_file_path):
                os.remove(converted_file_path)

    @abstractmethod
    async def _transcribe(self, audio: str, language: Optional[str] = None, model: Optional[str] = None,
                          **kwargs) -> str:
        """
        Internal Method: Convert Audio to Text

        Args:
            audio: Audio File Host, Files are automatically deleted when processing is complete
            language: Language code, e.g. 'zh', 'en'
            model: Used Model Name

        Returns:
            Transcribed text content
        """
        raise NotImplementedError


class BaseTTSClient(ABC):
    """TTS (Text To Speech) Base Interface Class"""

    @abstractmethod
    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: str = "mp3"
    ) -> bytes:
        """
        Synthesize text into speech

        Args:
            text: Text to compose
            voice: Audio Options
            language: Language code
            format: Audio formats, such as 'mp3', 'wav'

        Returns:
            Audio Bytes Data
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
