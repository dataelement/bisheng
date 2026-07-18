import asyncio
from typing import Optional

from dashscope.audio.tts_v2 import SpeechSynthesizer

from ..base import BaseTTSClient


class AliyunTTSClient(BaseTTSClient):
    """Alibaba CloudTTSClient"""

    def __init__(self, api_key: str, **kwargs):
        """
        Initialize Alibaba CloudTTSClient.

        dashscope SDK is designed for single-tenant usage and reads the apikey
        from the module-global ``dashscope.api_key`` at construction time —
        SpeechSynthesizer.__init__ does ``self.apikey = dashscope.api_key``
        and then ``self.request = Request(apikey=self.apikey, ...)``. Mutating
        ``dashscope.api_key`` would create a multi-tenant race window between
        the assignment and the construction call. Instead, we let construction
        happen with whatever the global currently holds (possibly None or a
        stale value) and immediately overwrite the apikey on both attributes
        the SDK uses at WS handshake time:

        - ``synthesizer.apikey`` — the synthesizer's own copy (read by some
          code paths in the SDK).
        - ``synthesizer.request.apikey`` — used by Request.getWebsocketHeaders
          to build the ``Authorization: bearer ...`` header at WS connect.

        This is multi-tenant safe because the SDK does **not** re-read the
        global after construction, so concurrent constructions cannot bleed
        keys across instances once their attributes are overwritten.

        Caveat: the ``qwen3-tts-flash-realtime`` family is served by a
        separate SDK class (``dashscope.audio.qwen_tts_realtime.QwenTtsRealtime``)
        with a different WS endpoint. Routing it through tts_v2.SpeechSynthesizer
        will fail at the server-side handshake. That model needs its own
        client subclass; this class is only the right adapter for
        cosyvoice-* / HTTP-based TTS models.
        """
        self.model = kwargs.get("model", "cosyvoice-v2")
        self.voice = kwargs.get("voice", "longxiaochun_v2")
        self.app_key = api_key
        self.synthesizer = SpeechSynthesizer(model=self.model, voice=self.voice)
        if api_key:
            self.synthesizer.apikey = api_key
            if getattr(self.synthesizer, 'request', None) is not None:
                self.synthesizer.request.apikey = api_key

    def sync_func(self, text: str):
        audio = self.synthesizer.call(text=text)
        return audio

    async def synthesize(
            self,
            text: str,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            format: str = "mp3"
    ) -> bytes:
        """
        Convert text to audio
        :param text:
        :param voice:
        :param language:
        :param format:
        :return:
        """

        audio = await asyncio.to_thread(self.sync_func, text=text)

        if audio is None:
            raise ValueError("TTS synthesis failed, no audio data returned.")

        return audio
