"""Optional Telegram bot - a secondary way to reach Jarvis. Enabled only when
TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID are set. Serves the owner's user ID
only; everyone else is ignored."""

from __future__ import annotations

import logging
from html import escape
from typing import TYPE_CHECKING

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..notify import Notice
from ..voice import VoiceError, synthesize
from . import ui

if TYPE_CHECKING:
    from ..core import Jarvis

log = logging.getLogger(__name__)

COMMANDS = [
    ("pomoc", "Šta umem i komande"), ("zadaci", "Otvoreni zadaci"), ("danas", "Brifing sada"),
    ("cekanje", "Nacrti na čekanju"), ("memorija", "Šta pamtim"), ("rezim", "tekst | glas | oba"),
    ("dnd", "Ne uznemiravaj on/off"), ("stop", "Pauziraj SVE odlazne akcije"), ("nastavi", "Ukini pauzu"),
    ("log", "Poslednjih 20 akcija"),
]


def action_keyboard(action_id: int, is_call: bool = False) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton("✅ Pozovi" if is_call else "✅ Pošalji", callback_data=f"ap:{action_id}:send")]
    if not is_call:
        buttons.append(InlineKeyboardButton("✏️ Izmeni", callback_data=f"ap:{action_id}:edit"))
    buttons.append(InlineKeyboardButton("❌ Odbij", callback_data=f"ap:{action_id}:reject"))
    return InlineKeyboardMarkup([buttons])


class TelegramBot:
    """Also acts as a Hub sink: Jarvis' notices are forwarded to Telegram."""

    def __init__(self, jarvis: "Jarvis"):
        self.j = jarvis
        self.owner_id = jarvis.cfg.owner_telegram_id
        self.app: Application = ApplicationBuilder().token(jarvis.cfg.telegram_bot_token).build()
        owner = filters.User(user_id=self.owner_id)
        self.app.add_handler(MessageHandler(owner & filters.COMMAND, self.cancel_edit), group=-1)
        self.app.add_handler(MessageHandler(owner & filters.COMMAND, self.on_command))
        self.app.add_handler(MessageHandler(owner & filters.TEXT & ~filters.COMMAND, self.on_text))
        self.app.add_handler(MessageHandler(owner & (filters.VOICE | filters.AUDIO), self.on_voice))
        self.app.add_handler(CallbackQueryHandler(self.on_callback))
        jarvis.hub.sinks.append(self)
        jarvis.telegram = self

    async def start(self) -> None:
        await self.app.initialize()
        await self.app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        log.info("Telegram bot running")

    async def stop(self) -> None:
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # --------------------------------------------------------------- sink ---
    async def deliver(self, n: Notice) -> None:
        if n.kind == "action" and n.action_id:
            action = self.j.queue.get(n.action_id)
            if action is None or action.status != "pending":
                return
            await self.app.bot.send_message(
                self.owner_id, ui.action_card(self.j.describe(action)), parse_mode=ParseMode.HTML,
                reply_markup=action_keyboard(action.id, action.kind == "call"),
            )
            return
        text = f"<b>{escape(n.title)}</b>" + (f"\n{escape(n.text)}" if n.text else "")
        for chunk in ui.split_text(text):
            await self.app.bot.send_message(self.owner_id, chunk, parse_mode=ParseMode.HTML)

    # ------------------------------------------------------------- chat -----
    async def cancel_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop("editing", None)

    async def on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, await self.j.chat(update.message.text, origin="telegram"), voice_ok=False)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        editing = context.user_data.pop("editing", None)
        if editing is not None:
            result = await self.j.decide(editing, "edit", update.message.text)
            if not result["ok"]:
                await update.message.reply_text(result["message"])
            else:
                await update.message.reply_text(
                    ui.action_card(result["action"]), parse_mode=ParseMode.HTML,
                    reply_markup=action_keyboard(editing),
                )
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        await self.reply(update, await self.j.chat(update.message.text, origin="telegram"))

    async def on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        media = update.message.voice or update.message.audio
        f = await media.get_file()
        audio = bytes(await f.download_as_bytearray())
        try:
            text = await self.j.transcriber.transcribe(audio, "voice.ogg")
        except VoiceError as exc:
            await update.message.reply_text(f"Ne mogu da prepoznam glas: {exc}")
            return
        if not text:
            await update.message.reply_text("Nisam ništa razumeo.")
            return
        await update.message.reply_text(f"🎙 „{text}”")
        await update.message.chat.send_action(ChatAction.TYPING)
        await self.reply(update, await self.j.chat(text, origin="telegram"))

    async def reply(self, update: Update, text: str, voice_ok: bool = True) -> None:
        mode = self.j.hub.voice_mode()
        if mode in ("tekst", "oba") or not voice_ok:
            for chunk in ui.split_text(text):
                await update.message.reply_text(chunk)
        if voice_ok and mode in ("glas", "oba"):
            try:
                audio = await synthesize(text, self.j.cfg.tts_voice)
                await update.message.reply_voice(audio)
            except VoiceError as exc:
                log.info("No voice reply: %s", exc)
                if mode == "glas":
                    await update.message.reply_text(text)

    # ---------------------------------------------------------- buttons -----
    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not update.effective_user or update.effective_user.id != self.owner_id:
            return  # silently ignore strangers
        data = query.data or ""
        if not data.startswith("ap:"):
            await query.answer()
            return
        _, raw_id, op = data.split(":")
        action_id = int(raw_id)
        if op == "edit":
            action = self.j.queue.get(action_id)
            if action is None or action.status != "pending":
                await query.answer("Taj nacrt više nije na čekanju.", show_alert=True)
                return
            context.user_data["editing"] = action_id
            await query.answer()
            await query.message.reply_text(f"✏️ Pošalji novi tekst za nacrt #{action_id} (bilo koja /komanda otkazuje).")
            return
        result = await self.j.decide(action_id, op)
        await query.answer(result["message"][:190], show_alert=not result["ok"])
        if "action" in result:
            mark = {"sent": "📤 <b>Poslato</b>", "rejected": "❌ <b>Odbijeno</b>", "failed": "⚠️ <b>Greška</b>"}
            status = mark.get(result["action"]["status"], escape(result["message"]))
            await query.edit_message_text(ui.action_card(result["action"]) + f"\n\n{status}", parse_mode=ParseMode.HTML)
        elif not result["ok"]:
            await query.edit_message_reply_markup(None)
