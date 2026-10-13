"""Entry point: ``python -m jarvis``. Starts the HUD server, the watchers,
the scheduler and (if configured) the Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .config import ConfigError, load_config


async def amain() -> None:
    cfg = load_config()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # never log tokens inside URLs
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    from aiohttp import web

    from .core import Jarvis
    from .web.server import create_app

    jarvis = Jarvis(cfg)
    runner = web.AppRunner(create_app(jarvis))
    await runner.setup()
    await web.TCPSite(runner, cfg.hud_host, cfg.hud_port).start()

    telegram = None
    if cfg.telegram_enabled:
        from .bot.app import TelegramBot

        telegram = TelegramBot(jarvis)
        await telegram.start()

    await jarvis.start()
    url = f"http://127.0.0.1:{cfg.hud_port}/?t={jarvis.hud_token}"
    (jarvis.data_dir / "hud_url.txt").write_text(url + "\n")
    print(f"\n  JARVIS je online.  HUD: {url}\n", flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    await stop.wait()

    logging.info("Shutting down…")
    if telegram:
        await telegram.stop()
    await runner.cleanup()
    await jarvis.stop()


def main() -> None:
    try:
        asyncio.run(amain())
    except ConfigError as exc:
        sys.exit(f"Config error: {exc}\nKopiraj .env.example u .env i popuni ga.")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
