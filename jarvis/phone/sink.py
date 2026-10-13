"""Delivers notices to the phone: Android notification (with approve/reject
buttons for drafts) and, for important things, Jarvis' voice out loud."""

from __future__ import annotations

import logging
import shlex
from pathlib import Path

from ..notify import Hub, Notice
from ..voice import VoiceError, clean_for_speech, synthesize
from .termux import NotificationButton, Termux

log = logging.getLogger(__name__)


class PhoneSink:
    def __init__(self, termux: Termux, hub: Hub, hud_url: str, token: str, tts_voice: str, audio_dir: str):
        self.termux = termux
        self.hub = hub
        self.hud_url = hud_url.rstrip("/")
        self.token = token
        self.tts_voice = tts_voice
        self.audio_dir = Path(audio_dir)

    def _api(self, path: str) -> str:
        return (
            f"curl -s -X POST -H {shlex.quote('X-Jarvis-Token: ' + self.token)} "
            f"{shlex.quote(self.hud_url + path)}"
        )

    async def deliver(self, n: Notice) -> None:
        open_hud = f"termux-open-url {shlex.quote(self.hud_url + '/')}"
        buttons = []
        if n.kind == "action" and n.action_id:
            buttons = [
                NotificationButton("✅ Pošalji", self._api(f"/api/actions/{n.action_id}/send")),
                NotificationButton("❌ Odbij", self._api(f"/api/actions/{n.action_id}/reject")),
                NotificationButton("✏️ Izmeni", open_hud),
            ]
        notif_id = f"jarvis-action-{n.action_id}" if n.action_id else f"jarvis-{n.id}"
        await self.termux.notify(notif_id, n.title, n.text or n.title, buttons, on_tap=open_hud, urgent=n.urgent)
        if n.speak and self.hub.voice_mode() in ("glas", "oba") and not self.hub.in_quiet_hours():
            await self.say(f"{n.title}. {n.text}")

    async def clear_action(self, action_id: int) -> None:
        try:
            await self.termux.remove_notification(f"jarvis-action-{action_id}")
        except Exception:  # noqa: BLE001
            pass

    async def say(self, text: str) -> None:
        text = clean_for_speech(text)[:600]
        try:
            audio = await synthesize(text, self.tts_voice)
            self.audio_dir.mkdir(parents=True, exist_ok=True)
            path = self.audio_dir / "jarvis_say.mp3"
            path.write_bytes(audio)
            await self.termux.play(str(path))
        except (VoiceError, OSError) as exc:
            log.info("edge-tts unavailable (%s); using Android TTS", exc)
            await self.termux.speak(text)
