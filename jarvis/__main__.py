"""Entry point: ``python -m jarvis``."""

import logging
import sys

from .config import ConfigError, load_config


def main() -> None:
    try:
        cfg = load_config()
    except ConfigError as exc:
        sys.exit(f"Config error: {exc}\nCopy .env.example to .env and fill it in.")

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log the bot token in URLs

    from .bot.app import JarvisBot

    try:
        bot = JarvisBot(cfg)
    except ConfigError as exc:
        sys.exit(f"Config error: {exc}")
    bot.run()


if __name__ == "__main__":
    main()
