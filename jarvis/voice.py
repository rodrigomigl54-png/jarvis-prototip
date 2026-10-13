"""Text-to-speech (edge-tts, free) and speech-to-text (Groq Whisper, free tier)."""

from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger(__name__)

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
VOICE_MODES = ("tekst", "glas", "oba")


class VoiceError(Exception):
    pass


def clean_for_speech(text: str) -> str:
    """Drop markdown symbols and emoji that TTS would read out loud."""
    text = re.sub(r"[*_`#>\[\]]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)
    return re.sub(r"\s+", " ", text).strip()


async def synthesize(text: str, voice: str = "sr-RS-NicholasNeural") -> bytes:
    """MP3 bytes in a Serbian neural voice. Needs internet; no API key."""
    import edge_tts  # imported lazily: optional at test time

    text = clean_for_speech(text)
    if not text:
        raise VoiceError("nothing to say")
    audio = bytearray()
    try:
        async for chunk in edge_tts.Communicate(text[:3000], voice).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except Exception as exc:  # noqa: BLE001 - network / service errors
        raise VoiceError(f"edge-tts failed: {exc}") from exc
    if not audio:
        raise VoiceError("edge-tts returned no audio")
    return bytes(audio)


class Transcriber:
    def __init__(self, groq_api_key: str, model: str = "whisper-large-v3-turbo", client: httpx.AsyncClient | None = None):
        self.enabled = bool(groq_api_key)
        self.model = model
        self._client = client or httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {groq_api_key}"})

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if not self.enabled:
            raise VoiceError("GROQ_API_KEY is not set - voice messages need it")
        resp = await self._client.post(
            GROQ_STT_URL,
            data={"model": self.model, "language": "sr", "response_format": "json"},
            files={"file": (filename, audio)},
        )
        if resp.status_code >= 400:
            raise VoiceError(f"Groq STT HTTP {resp.status_code}: {resp.text[:200]}")
        return (resp.json().get("text") or "").strip()

    async def aclose(self) -> None:
        await self._client.aclose()
