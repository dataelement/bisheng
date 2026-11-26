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


def test_aliyun_routes_file_models() -> None:
    assert aliyun_asr_client.asr_call_kind("qwen-audio-3.0-asr-flash-filetrans") == "transcription"
    assert aliyun_asr_client.asr_call_kind("fun-asr-2025-11-07") == "transcription"
    assert aliyun_asr_client.asr_call_kind("fun-asr-mtl") == "transcription"
    assert aliyun_asr_client.asr_call_kind("paraformer-v2") == "transcription"
    assert aliyun_asr_client.asr_call_kind("paraformer-8k-v2") == "transcription"
    assert aliyun_asr_client.asr_call_kind("paraformer-realtime-v2") == "recognition"
    assert aliyun_asr_client.asr_call_kind("qwen3-asr-flash-2026-02-10") == "qwen3"
    assert aliyun_asr_client.asr_call_kind("qwen3-asr-flash-realtime") == "recognition"
    assert aliyun_asr_client.asr_call_kind("qwen3-asr-flash-filetrans-2025-11-17") == "unsupported"
    assert aliyun_asr_client.asr_call_kind("qwen-audio-3.0-asr-flash") == "input_audio"
    assert aliyun_asr_client.asr_call_kind("qwen-audio-3.1-asr-flash-streaming") == "recognition"
    assert aliyun_asr_client.asr_call_kind("fun-asr-flash-2026-06-15") == "input_audio"
    assert aliyun_asr_client.asr_call_kind("fun-asr-flash-8k-realtime") == "recognition"


def test_dashscope_refuses_private_transcription_urls() -> None:
    assert aliyun_asr_client.dashscope_can_get("https://oss.example.com/a.wav")
    assert not aliyun_asr_client.dashscope_can_get("http://192.168.106.107:9100/tmp/a.wav")
    assert not aliyun_asr_client.dashscope_can_get("http://127.0.0.1:9000/a.wav")
    assert not aliyun_asr_client.dashscope_can_get("http://localhost/a.wav")
    assert not aliyun_asr_client.dashscope_can_get("/tmp-dir/a.wav")


class _FakeMultiModal:
    result = None
    calls: list[dict] = []

    @staticmethod
    def call(**kwargs):
        _FakeMultiModal.calls.append(kwargs)
        return _FakeMultiModal.result


class _FakeTranscription:
    result = None
    calls: list[dict] = []

    @staticmethod
    def call(**kwargs):
        _FakeTranscription.calls.append(kwargs)
        return _FakeTranscription.result


def _http_ok(output):
    return SimpleNamespace(status_code=200, code="", message="", output=output)


def test_qwen_audio_flash_uses_input_audio(monkeypatch, tmp_path) -> None:
    wav_path = tmp_path / "a.wav"
    wav_path.write_bytes(b"RIFFwav")
    _FakeMultiModal.calls = []
    _FakeMultiModal.result = _http_ok({"text": "你好", "choices": None})
    monkeypatch.setattr(aliyun_asr_client.dashscope, "MultiModalConversation", _FakeMultiModal)
    client = AliyunASRClient(api_key="sk-test", model="qwen-audio-3.0-asr-flash")

    transcript = asyncio.run(client.transcribe_file(str(wav_path)))

    assert transcript.text == "你好"
    assert transcript.segments == []
    call = _FakeMultiModal.calls[0]
    assert call["model"] == "qwen-audio-3.0-asr-flash"
    assert call["format"] == "wav"
    assert call["sample_rate"] == "16000"
    content = call["messages"][0]["content"][0]
    assert content["type"] == "input_audio"
    assert content["input_audio"]["data"].startswith("data:audio/wav;base64,")


def test_qwen3_reads_choice_text_list(monkeypatch) -> None:
    class _Message:
        content = [{"text": "实验室"}]

    _FakeMultiModal.calls = []
    _FakeMultiModal.result = _http_ok({"choices": [{"message": _Message()}]})
    monkeypatch.setattr(aliyun_asr_client.dashscope, "MultiModalConversation", _FakeMultiModal)
    client = AliyunASRClient(api_key="sk-test", model="qwen3-asr-flash")

    transcript = asyncio.run(client.transcribe_file("/tmp/fake.wav"))

    assert transcript.text == "实验室"
    content = _FakeMultiModal.calls[0]["messages"][0]["content"][0]
    assert content == {"audio": "/tmp/fake.wav"}
    assert _FakeMultiModal.calls[0]["result_format"] == "message"


def test_qwen3_filetrans_fails_before_any_call(monkeypatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("qwen3 filetrans must not call DashScope")

    monkeypatch.setattr(aliyun_asr_client, "Recognition", _forbidden)
    monkeypatch.setattr(aliyun_asr_client, "Transcription", _forbidden)
    monkeypatch.setattr(aliyun_asr_client.dashscope, "MultiModalConversation", _forbidden)
    client = AliyunASRClient(api_key="sk-test", model="qwen3-asr-flash-filetrans-2025-11-17")

    try:
        asyncio.run(client.transcribe_file("/tmp/fake.wav"))
    except RuntimeError as exc:
        assert "file_url" in str(exc)
    else:
        raise AssertionError("expected qwen3 filetrans to fail")


def test_transcription_maps_sentences_and_skips_recognition(monkeypatch) -> None:
    _FakeTranscription.calls = []
    _FakeTranscription.result = _http_ok(
        {
            "task_status": "SUCCEEDED",
            "results": [
                {
                    "subtask_status": "SUCCEEDED",
                    "transcription_url": "https://dashscope.example.com/result.json",
                }
            ],
        }
    )
    monkeypatch.setattr(aliyun_asr_client, "Transcription", _FakeTranscription)
    monkeypatch.setattr(aliyun_asr_client, "publish_transcription_wav", lambda _path: "https://oss.example.com/a.wav")
    monkeypatch.setattr(
        aliyun_asr_client,
        "download_transcription_json",
        lambda _url: {
            "transcripts": [
                {
                    "sentences": [
                        {"text": "第一句。", "begin_time": 100, "end_time": 800},
                        {"text": "第二句。", "begin_time": 800, "end_time": 1500},
                    ]
                }
            ]
        },
    )
    monkeypatch.setattr(
        aliyun_asr_client, "Recognition", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("recognition"))
    )
    client = AliyunASRClient(api_key="sk-test", model="fun-asr")

    transcript = asyncio.run(client.transcribe_file("/tmp/fake.wav"))

    assert transcript.text == "第一句。第二句。"
    assert transcript.segments == [
        ASRSegment("第一句。", begin_ms=100.0, end_ms=800.0),
        ASRSegment("第二句。", begin_ms=800.0, end_ms=1500.0),
    ]
    assert _FakeTranscription.calls[0]["file_urls"] == ["https://oss.example.com/a.wav"]
    assert _FakeTranscription.calls[0]["model"] == "fun-asr"


def test_transcription_upload_failure_does_not_call_dashscope(monkeypatch) -> None:
    def _upload(_path):
        raise RuntimeError("share address is private")

    monkeypatch.setattr(aliyun_asr_client, "publish_transcription_wav", _upload)
    monkeypatch.setattr(
        aliyun_asr_client, "Transcription", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("call"))
    )
    client = AliyunASRClient(api_key="sk-test", model="paraformer-v2")

    try:
        asyncio.run(client.transcribe_file("/tmp/fake.wav"))
    except RuntimeError as exc:
        assert "private" in str(exc)
    else:
        raise AssertionError("expected upload failure")


def test_paraformer_8k_uploads_resampled_wav(monkeypatch) -> None:
    seen: list[str] = []

    def _resample(path):
        assert path == "/tmp/fake.wav"
        return "/tmp/fake-8k.wav"

    def _upload(path):
        seen.append(path)
        return "https://oss.example.com/8k.wav"

    _FakeTranscription.calls = []
    _FakeTranscription.result = _http_ok(
        {
            "task_status": "SUCCEEDED",
            "results": [{"subtask_status": "SUCCEEDED", "transcription_url": "https://dashscope.example.com/r.json"}],
        }
    )
    monkeypatch.setattr(aliyun_asr_client, "resample_wav_8k", _resample)
    monkeypatch.setattr(aliyun_asr_client, "publish_transcription_wav", _upload)
    monkeypatch.setattr(aliyun_asr_client, "download_transcription_json", lambda _url: {"transcripts": []})
    monkeypatch.setattr(aliyun_asr_client, "Transcription", _FakeTranscription)
    client = AliyunASRClient(api_key="sk-test", model="paraformer-8k-v1")

    transcript = asyncio.run(client.transcribe_file("/tmp/fake.wav"))

    assert seen == ["/tmp/fake-8k.wav"]
    assert transcript.text == ""
    assert _FakeTranscription.calls[0]["model"] == "paraformer-8k-v1"


def test_transcription_http_error_does_not_read_output(monkeypatch) -> None:
    class _Output:
        def __getitem__(self, _key):
            raise AssertionError("output must not be read")

    _FakeTranscription.result = SimpleNamespace(
        status_code=400, code="InvalidParameter", message="bad url", output=_Output()
    )
    monkeypatch.setattr(aliyun_asr_client, "Transcription", _FakeTranscription)
    monkeypatch.setattr(aliyun_asr_client, "publish_transcription_wav", lambda _path: "https://oss.example.com/a.wav")
    client = AliyunASRClient(api_key="sk-test", model="paraformer-v1")

    try:
        asyncio.run(client.transcribe_file("/tmp/fake.wav"))
    except RuntimeError as exc:
        assert "InvalidParameter" in str(exc)
    else:
        raise AssertionError("expected HTTP error")


def test_transcription_failed_subtask_raises(monkeypatch) -> None:
    _FakeTranscription.result = _http_ok(
        {
            "task_status": "SUCCEEDED",
            "results": [{"subtask_status": "FAILED", "message": "decode failed"}],
        }
    )
    monkeypatch.setattr(aliyun_asr_client, "Transcription", _FakeTranscription)
    monkeypatch.setattr(aliyun_asr_client, "publish_transcription_wav", lambda _path: "https://oss.example.com/a.wav")
    client = AliyunASRClient(api_key="sk-test", model="paraformer-mtl-v1")

    try:
        asyncio.run(client.transcribe_file("/tmp/fake.wav"))
    except RuntimeError as exc:
        assert "decode failed" in str(exc)
    else:
        raise AssertionError("expected subtask failure")


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
