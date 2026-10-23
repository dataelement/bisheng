"""Provider ASR clients: the shared layer under workbench voice input and media transcription."""

import asyncio
from types import SimpleNamespace

import httpx
import openai

from bisheng.core.ai.asr import aliyun_asr_client
from bisheng.core.ai.asr.aliyun_asr_client import AliyunASRClient
from bisheng.core.ai.asr.openai_asr_client import transcribe_with_openai_sdk
from bisheng.core.ai.base import ASRSegment, join_sentence_texts


class _FakeRecognition:
    result = None

    def __init__(self, **kwargs) -> None:
        pass

    def call(self, wav_path, api_key=None):
        return type(self).result


def _aliyun_transcribe(monkeypatch, result):
    _FakeRecognition.result = result
    monkeypatch.setattr(aliyun_asr_client, "Recognition", _FakeRecognition)
    client = AliyunASRClient(api_key="sk-test", model="paraformer-realtime-v2")
    return asyncio.run(client.transcribe_file("/tmp/fake.wav"))


def _aliyun_result(sentences, output):
    return SimpleNamespace(status_code=200, code="", message="", output=output, get_sentence=lambda: sentences)


def test_aliyun_returns_every_sentence_with_timestamps(monkeypatch) -> None:
    result = _aliyun_result(
        [
            {"text": "第一句。", "begin_time": 0, "end_time": 1200},
            {"text": "第二句。", "begin_time": 1200, "end_time": 3000},
        ],
        output={},
    )

    transcript = _aliyun_transcribe(monkeypatch, result)

    # Voice input used to keep only the first sentence.
    assert transcript.text == "第一句。第二句。"
    assert transcript.segments == [
        ASRSegment("第一句。", begin_ms=0.0, end_ms=1200.0),
        ASRSegment("第二句。", begin_ms=1200.0, end_ms=3000.0),
    ]


def test_aliyun_null_output_returns_empty_transcript(monkeypatch) -> None:
    """A 200 response with no sentences and output=null must NOT surface the raw
    JSON envelope as recognized text."""
    transcript = _aliyun_transcribe(monkeypatch, _aliyun_result(None, output=None))

    assert transcript.text == ""
    assert transcript.segments == []


def test_aliyun_empty_sentence_list_returns_empty_transcript(monkeypatch) -> None:
    transcript = _aliyun_transcribe(monkeypatch, _aliyun_result([], output={"sentence": []}))

    assert transcript.text == ""


def test_aliyun_plain_text_output_fallback(monkeypatch) -> None:
    transcript = _aliyun_transcribe(monkeypatch, _aliyun_result([], output={"text": "hello world"}))

    assert transcript.text == "hello world"
    assert transcript.segments == []


def test_join_sentence_texts_spaces_only_latin_words() -> None:
    assert join_sentence_texts(["Hello.", "World."]) == "Hello. World."
    assert join_sentence_texts(["你好。", "世界。"]) == "你好。世界。"
    assert join_sentence_texts(["  ", "单独"]) == "单独"


class _FakeTranscriptions:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        kwargs.pop("file")
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _openai_transcribe(responses, tmp_path, language=None):
    wav_path = tmp_path / "a.wav"
    wav_path.write_bytes(b"fake wav")
    transcriptions = _FakeTranscriptions(responses)
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    transcript = asyncio.run(
        transcribe_with_openai_sdk(client, str(wav_path), model="whisper-large-v3", language=language)
    )
    return transcript, transcriptions.calls


def test_openai_verbose_segments_are_converted_to_milliseconds(tmp_path) -> None:
    response = SimpleNamespace(
        text="Hello world. Second part.",
        segments=[
            SimpleNamespace(text=" Hello world.", start=0.0, end=1.5),
            {"text": " Second part.", "start": 1.5, "end": 3.25},
        ],
    )

    transcript, calls = _openai_transcribe([response], tmp_path)

    assert transcript.text == "Hello world. Second part."
    assert transcript.segments == [
        ASRSegment("Hello world.", begin_ms=0.0, end_ms=1500.0),
        ASRSegment("Second part.", begin_ms=1500.0, end_ms=3250.0),
    ]
    assert calls == [{"model": "whisper-large-v3", "response_format": "verbose_json"}]


def test_openai_falls_back_to_plain_request_when_verbose_rejected(tmp_path) -> None:
    request = httpx.Request("POST", "http://asr.local/v1/audio/transcriptions")
    rejected = openai.BadRequestError(
        "response_format 'verbose_json' is not compatible",
        response=httpx.Response(400, request=request),
        body=None,
    )

    transcript, calls = _openai_transcribe([rejected, SimpleNamespace(text="纯文本结果")], tmp_path)

    assert transcript.text == "纯文本结果"
    assert transcript.segments == []
    assert calls == [
        {"model": "whisper-large-v3", "response_format": "verbose_json"},
        {"model": "whisper-large-v3"},
    ]


def test_openai_omits_auto_language(tmp_path) -> None:
    _, calls = _openai_transcribe([SimpleNamespace(text="x")], tmp_path, language="auto")
    assert "language" not in calls[0]

    _, calls = _openai_transcribe([SimpleNamespace(text="x")], tmp_path, language="zh")
    assert calls[0]["language"] == "zh"
