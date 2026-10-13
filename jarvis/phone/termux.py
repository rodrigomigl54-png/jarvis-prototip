"""Android access through Termux:API (https://wiki.termux.com/wiki/Termux:API).

Jarvis runs inside Termux on the phone; every ``termux-*`` command below talks
to the Termux:API app, which holds the Android permissions (SMS, call log,
contacts, notifications). Install both apps from F-Droid - the Google Play
builds are not allowed to read SMS or the call log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


class PhoneError(Exception):
    pass


@dataclass
class NotificationButton:
    label: str
    action: str  # shell command run by Termux when tapped


def termux_available() -> bool:
    return shutil.which("termux-sms-send") is not None


class Termux:
    """Thin async wrapper. Every method maps to one termux-* command."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def _run(self, *args: str, stdin: str | None = None) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin is not None else None), self.timeout
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise PhoneError(f"{args[0]} timed out") from exc
        if proc.returncode != 0:
            raise PhoneError(f"{args[0]} failed: {err.decode(errors='replace').strip()}")
        return out.decode(errors="replace")

    async def _json(self, *args: str) -> Any:
        raw = (await self._run(*args)).strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PhoneError(f"{args[0]} returned non-JSON: {raw[:200]}") from exc
        if isinstance(data, dict) and "error" in data:
            raise PhoneError(f"{args[0]}: {data['error']}")
        return data

    # --- reading ---
    async def call_log(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._json("termux-call-log", "-l", str(limit))

    async def sms_inbox(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._json("termux-sms-list", "-t", "inbox", "-l", str(limit))

    async def contacts(self) -> list[dict[str, Any]]:
        return await self._json("termux-contact-list")

    async def notifications(self) -> list[dict[str, Any]]:
        return await self._json("termux-notification-list")

    async def battery(self) -> dict[str, Any]:
        return await self._json("termux-battery-status")

    # --- acting (only ever called by the Executor or for the owner's own notifications) ---
    async def sms_send(self, number: str, text: str) -> None:
        await self._run("termux-sms-send", "-n", number, text)

    async def call(self, number: str) -> None:
        await self._run("termux-telephony-call", number)

    async def open_url(self, url: str) -> None:
        await self._run("termux-open-url", url)

    # --- talking to the owner ---
    async def notify(
        self,
        notif_id: str,
        title: str,
        content: str,
        buttons: list[NotificationButton] | None = None,
        on_tap: str | None = None,
        urgent: bool = False,
    ) -> None:
        args = ["termux-notification", "--id", notif_id, "--title", title, "--content", content,
                "--group", "jarvis"]
        if urgent:
            args += ["--priority", "max", "--vibrate", "300,150,300", "--sound"]
        else:
            args += ["--priority", "default"]
        if on_tap:
            args += ["--action", on_tap]
        for i, b in enumerate((buttons or [])[:3], 1):
            args += [f"--button{i}", b.label, f"--button{i}-action", b.action]
        await self._run(*args)

    async def remove_notification(self, notif_id: str) -> None:
        await self._run("termux-notification-remove", notif_id)

    async def play(self, path: str) -> None:
        await self._run("termux-media-player", "play", path)

    async def speak(self, text: str) -> None:
        """Android's built-in TTS; used when edge-tts (online) is unavailable."""
        await self._run("termux-tts-speak", "-l", "sr", text)

    async def wake_lock(self) -> None:
        await self._run("termux-wake-lock")
