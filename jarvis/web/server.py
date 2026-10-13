"""HUD web server (aiohttp). Listens on 127.0.0.1 only: the HUD is opened in
the phone's browser. Every /api call needs the HUD token."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from aiohttp import web

from ..google import format_event
from ..voice import VoiceError, synthesize

if TYPE_CHECKING:
    from ..core import Jarvis

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class Cache:
    """Tiny time-based cache so the HUD doesn't hammer weather/calendar APIs."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str, ttl: float, fetch: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await fetch()
        self._data[key] = (time.monotonic(), value)
        return value


def create_app(j: "Jarvis") -> web.Application:
    cache = Cache()

    def token_ok(request: web.Request) -> bool:
        given = request.headers.get("X-Jarvis-Token") or request.query.get("t") or ""
        return secrets.compare_digest(given, j.hud_token)

    def bridge_ok(request: web.Request) -> bool:
        given = request.headers.get("X-Bridge-Token") or ""
        return bool(j.cfg.whatsapp_bridge_token) and secrets.compare_digest(given, j.cfg.whatsapp_bridge_token)

    @web.middleware
    async def auth(request: web.Request, handler: Handler) -> web.StreamResponse:
        path = request.path
        if path.startswith("/api/hooks/"):
            if not bridge_ok(request):
                return web.json_response({"error": "unauthorized"}, status=401)
        elif path.startswith("/api/") and not token_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    app = web.Application(middlewares=[auth], client_max_size=15 * 1024 * 1024)

    # ---------------------------------------------------------------- pages ---
    async def index(request: web.Request) -> web.StreamResponse:
        # Google OAuth redirects back here with ?code=...&state=...
        if "code" in request.query and "state" in request.query and j.google:
            try:
                await j.google.finish_login(request.query["code"], request.query["state"])
                await j.hub.notify("info", "✅ Google povezan", "Gmail i kalendar su spremni.")
            except Exception as exc:  # noqa: BLE001
                log.warning("Google login failed: %s", exc)
                return web.Response(text=f"Google povezivanje nije uspelo: {exc}", status=400)
            raise web.HTTPFound("/")
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    # ----------------------------------------------------------------- API ---
    async def state(request: web.Request) -> web.Response:
        data = j.state()
        if j.termux:
            try:
                data["battery"] = await cache.get("battery", 60, j.termux.battery)
            except Exception:  # noqa: BLE001
                data["battery"] = None
        return web.json_response(data, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))

    async def chat(request: web.Request) -> web.Response:
        body = await request.json()
        text = str(body.get("text", ""))[:4000]
        reply = await j.chat(text, origin=str(body.get("client_id", "")))
        return web.json_response({"reply": reply, "voice_mode": j.hub.voice_mode()})

    async def tts(request: web.Request) -> web.Response:
        body = await request.json()
        try:
            audio = await synthesize(str(body.get("text", "")), j.cfg.tts_voice)
        except VoiceError as exc:
            return web.json_response({"error": str(exc)}, status=503)
        return web.Response(body=audio, content_type="audio/mpeg")

    async def stt(request: web.Request) -> web.Response:
        reader = await request.multipart()
        part = await reader.next()
        if part is None:
            return web.json_response({"error": "no audio"}, status=400)
        audio = await part.read(decode=False)
        try:
            text = await j.transcriber.transcribe(bytes(audio), part.filename or "voice.webm")
        except VoiceError as exc:
            return web.json_response({"error": str(exc)}, status=503)
        return web.json_response({"text": text})

    async def action(request: web.Request) -> web.Response:
        action_id = int(request.match_info["id"])
        op = request.match_info["op"]
        new_text = None
        if request.can_read_body:
            try:
                new_text = (await request.json()).get("text")
            except (json.JSONDecodeError, ValueError):
                new_text = None
        return web.json_response(await j.decide(action_id, op, new_text), dumps=lambda o: json.dumps(o, default=str))

    async def weather(request: web.Request) -> web.Response:
        try:
            data = await cache.get("weather", 900, j.web.weather_data)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=503)
        return web.json_response({"city": j.cfg.city, **data})

    async def calendar(request: web.Request) -> web.Response:
        if not (j.calendar and j.google and j.google.connected):
            return web.json_response({"events": [], "connected": False})

        async def fetch():
            return [format_event(e) for e in await j.calendar.day(datetime.now(j.calendar.tz))]

        try:
            events = await cache.get("calendar", 300, fetch)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"events": [], "connected": True, "error": str(exc)})
        return web.json_response({"events": events, "connected": True})

    async def google_login(request: web.Request) -> web.StreamResponse:
        if not j.google:
            return web.json_response({"error": "Google not configured"}, status=400)
        raise web.HTTPFound(j.google.login_url())

    async def events(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(request)
        q = j.hub.subscribe()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=20)
                    payload = json.dumps(item["data"], ensure_ascii=False, default=str)
                    await resp.write(f"event: {item['event']}\ndata: {payload}\n\n".encode())
                except asyncio.TimeoutError:
                    await resp.write(b": ping\n\n")  # keeps the connection alive
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            j.hub.unsubscribe(q)
        return resp

    # ---------------------------------------------------- WhatsApp bridge ---
    async def wa_hook(request: web.Request) -> web.Response:
        await j.on_whatsapp_bridge(await request.json())
        return web.json_response({"ok": True})

    async def wa_call(request: web.Request) -> web.Response:
        await j.on_whatsapp_bridge_call(await request.json())
        return web.json_response({"ok": True})

    async def wa_pairing(request: web.Request) -> web.Response:
        await j.on_whatsapp_pairing(str((await request.json()).get("code", "")))
        return web.json_response({"ok": True})

    app.router.add_get("/", index)
    app.router.add_static("/static", STATIC)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/events", events)
    app.router.add_post("/api/chat", chat)
    app.router.add_post("/api/tts", tts)
    app.router.add_post("/api/stt", stt)
    app.router.add_post(r"/api/actions/{id:\d+}/{op:send|reject|edit}", action)
    app.router.add_get("/api/weather", weather)
    app.router.add_get("/api/calendar", calendar)
    app.router.add_get("/api/google/login", google_login)
    app.router.add_post("/api/hooks/whatsapp", wa_hook)
    app.router.add_post("/api/hooks/whatsapp/pairing", wa_pairing)
    app.router.add_post("/api/hooks/whatsapp/call", wa_call)
    return app
