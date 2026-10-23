import asyncio
import os
import tempfile
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import BinaryIO, Union

import aiofiles
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import ConfigDict


class BaseASRClient(ABC):
    """ASR (Automatic Speech Recognition) Base Interface Class"""

    async def transcribe(
        self, audio: Union[str, bytes, BinaryIO], language: str | None = None, model: str | None = None, **kwargs
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
            with open(audio, "rb") as audio_file:
                audio_bytes = audio_file.read()
        elif isinstance(audio, bytes):
            audio_bytes = audio
        elif hasattr(audio, "read"):
            audio_bytes = audio.read()
        else:
            raise ValueError("Invalid audio input type")
        tmp_dir = tempfile.gettempdir()

        tmp_file_path = os.path.join(tmp_dir, uuid.uuid4().hex + ".wav")
        # ffmpeg Convert To16kSampling Rate MonowavDoc.
        converted_file_path = os.path.join(tmp_dir, uuid.uuid4().hex + "_16k_mono.wav")

        try:
            async with aiofiles.open(tmp_file_path, "wb") as f:
                await f.write(audio_bytes)

            command = f'ffmpeg -y -i "{tmp_file_path}" -ar 16000 -ac 1 "{converted_file_path}"'
            process = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            await process.communicate()

            result = await self.transcribe_file(converted_file_path, language=language, model=model)
            return result.text
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
            if os.path.exists(converted_file_path):
                os.remove(converted_file_path)

    @abstractmethod
    async def transcribe_file(
        self,
        wav_path: str,
        language: str | None = None,
        model: str | None = None,
    ) -> "ASRTranscript":
        """
        Transcribe a local 16k mono wav file.

        The single provider entry point shared by workbench voice input (reads
        ``text``) and knowledge media transcription (reads ``segments``).

        Args:
            wav_path: 16k mono wav file; the caller owns and deletes it
            language: Language code, e.g. 'zh', 'en'; None lets the provider detect
            model: Overrides the model name bound to the client
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release network resources held by the client."""


@dataclass
class ASRSegment:
    text: str
    # Milliseconds when the provider reports timing; None otherwise.
    begin_ms: float | None = None
    end_ms: float | None = None


@dataclass
class ASRTranscript:
    text: str
    # Empty when the provider only returns plain text.
    segments: list[ASRSegment] = field(default_factory=list)


def join_sentence_texts(texts: Sequence[str]) -> str:
    """Join recognized sentences, inserting a space only between Latin-script words."""
    joined = ""
    for text in texts:
        text = text.strip()
        if not text:
            continue
        if joined and joined[-1].isascii() and not joined[-1].isspace() and text[0].isascii() and text[0].isalnum():
            joined += " "
        joined += text
    return joined


class BaseTTSClient(ABC):
    """TTS (Text To Speech) Base Interface Class"""

    @abstractmethod
    async def synthesize(
        self, text: str, voice: str | None = None, language: str | None = None, format: str = "mp3"
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
        callbacks: Callbacks | None = None,
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
