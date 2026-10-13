"""Telegram bot wiring. Only the owner's user ID is served; everyone else is ignored."""

from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..agent import Agent
from ..approval import ApprovalQueue, Executor, PendingAction
from ..audit import AuditLog
from ..channels.test_channel import TestChannel
from ..config import Config
from ..db import Database
from ..llm import create_provider
from ..memory import Memory
from ..tools import ToolContext, load_tools
from . import ui

log = logging.getLogger(__name__)

COMMANDS = [
    ("pomoc", "Šta umem i komande"),
    ("memorija", "Šta pamtim (i brisanje)"),
    ("cekanje", "Nacrti koji čekaju odobrenje"),
    ("log", "Poslednjih 20 akcija"),
    ("stop", "Pauziraj SVE odlazne akcije"),
    ("nastavi", "Ukini pauzu"),
    ("test", "Probaj odobravanje: /test tekst"),
    ("reset", "Zaboravi tekući razgovor (ne i memoriju)"),
]

HELP = """Ćao, ja sam Jarvis. 🎩

Piši mi normalno, npr:
• „zapamti da pijem kafu bez šećera”
• „koliko je sati?”
• „pošalji Marku na test kanal da kasnim 10 min”

Ništa ne šaljem nikome bez tvog ✅. Komande:
/memorija – šta pamtim
/cekanje – nacrti na čekanju
/log – poslednjih 20 akcija
/stop – zaustavi sve odlazne akcije  ·  /nastavi – nastavi
/test &lt;tekst&gt; – probni nacrt na test kanalu
/reset – zaboravi tekući razgovor"""


class JarvisBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.audit = AuditLog(self.db)
        self.memory = Memory(self.db, cfg.history_limit)
        self.queue = ApprovalQueue(self.db, self.audit)
        self.executor = Executor(self.queue)
        self.llm = create_provider(cfg)
        self.agent = Agent(self.llm, self.memory, load_tools())
        self.app: Application = (
            ApplicationBuilder().token(cfg.telegram_bot_token).post_init(self._post_init)
            .post_shutdown(self._post_shutdown).build()
        )
        self.executor.register(TestChannel(self.notify_owner))
        self._register_handlers()

    # ---------- setup ----------
    def _register_handlers(self) -> None:
        owner = filters.User(user_id=self.cfg.owner_telegram_id)
        # Any command cancels a pending "edit draft" prompt.
        self.app.add_handler(MessageHandler(owner & filters.COMMAND, self._cancel_edit), group=-1)

        for name, handler in [
            ("start", self.cmd_help), ("pomoc", self.cmd_help), ("help", self.cmd_help),
            ("memorija", self.cmd_memory), ("cekanje", self.cmd_pending), ("log", self.cmd_log),
            ("stop", self.cmd_stop), ("nastavi", self.cmd_resume), ("test", self.cmd_test),
            ("reset", self.cmd_reset),
        ]:
            self.app.add_handler(CommandHandler(name, handler, filters=owner))
        self.app.add_handler(MessageHandler(owner & filters.TEXT & ~filters.COMMAND, self.on_text))
        self.app.add_handler(CallbackQueryHandler(self.on_callback))
        self.app.add_error_handler(self._on_error)

    async def _post_init(self, app: Application) -> None:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
        log.info("Jarvis is up. LLM provider: %s", self.llm.name)

    async def _post_shutdown(self, app: Application) -> None:
        await self.llm.aclose()
        self.db.close()

    def run(self) -> None:
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    # ---------- helpers ----------
    def _is_owner(self, update: Update) -> bool:
        return bool(update.effective_user and update.effective_user.id == self.cfg.owner_telegram_id)

    async def notify_owner(self, text: str) -> None:
        for chunk in ui.split_text(text):
            await self.app.bot.send_message(self.cfg.owner_telegram_id, chunk)

    async def show_action(self, action: PendingAction) -> None:
        await self.app.bot.send_message(
            self.cfg.owner_telegram_id, ui.action_card(action),
            parse_mode=ParseMode.HTML, reply_markup=ui.action_keyboard(action.id),
        )

    async def on_new_action(self, action: PendingAction) -> None:
        if action.status == "approved":  # matched an auto rule
            result = await self.executor.execute(action.id)
            await self.notify_owner(f"🤖 Auto-poslato #{action.id}: {result.reason}")
        else:
            await self.show_action(action)

    def tool_context(self) -> ToolContext:
        return ToolContext(
            memory=self.memory, queue=self.queue, timezone=self.cfg.timezone, owner_name=self.cfg.owner_name,
            available_channels=sorted(self.executor.channels), on_new_action=self.on_new_action,
        )

    # ---------- chat ----------
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text
        editing = context.user_data.pop("editing", None)
        if editing is not None:
            action = self.queue.edit(editing, text)
            if action is None:
                await update.message.reply_text("Taj nacrt više nije na čekanju.")
            else:
                await self.show_action(action)
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        reply = await self.agent.handle(text, self.tool_context())
        for chunk in ui.split_text(reply):
            await update.message.reply_text(chunk)

    # ---------- commands ----------
    async def _cancel_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop("editing", None)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)

    async def cmd_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text, kb = ui.facts_view(self.memory.facts())
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    async def cmd_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        actions = self.queue.list_by_status("pending")
        if not actions:
            await update.message.reply_text("Ništa ne čeka odobrenje. 👌")
        for a in actions:
            await self.show_action(a)

    async def cmd_log(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            ui.audit_view(self.audit.recent(20), self.cfg.timezone), parse_mode=ParseMode.HTML
        )

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.queue.set_paused(True)
        await update.message.reply_text("⏸ Sve odlazne akcije su pauzirane. Ništa ne izlazi dok ne kažeš /nastavi.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.queue.set_paused(False)
        await update.message.reply_text("▶️ Nastavljam. Nacrti i dalje čekaju tvoje ✅.")

    async def cmd_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = " ".join(context.args) or "Ćao! Ovo je probna poruka od Jarvisa."
        action = self.queue.submit("message", "test", "Test primalac", {"text": text}, source="owner:/test")
        await self.on_new_action(action)

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.memory.clear_history()
        await update.message.reply_text("🧹 Tekući razgovor obrisan. Dugoročna memorija je ostala.")

    # ---------- buttons ----------
    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_owner(update):
            return  # silently ignore strangers
        data = query.data or ""

        if data.startswith("mem:del:"):
            ok = self.memory.forget(int(data.split(":")[2]))
            await query.answer("Obrisano." if ok else "Već obrisano.")
            text, kb = ui.facts_view(self.memory.facts())
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return

        if data.startswith("ap:"):
            _, raw_id, op = data.split(":")
            await self._handle_action_button(update, context, int(raw_id), op)
            return

        await query.answer()

    async def _handle_action_button(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_id: int, op: str
    ) -> None:
        query = update.callback_query
        action = self.queue.get(action_id)
        if action is None or action.status != "pending":
            await query.answer(f"Nacrt #{action_id} više nije na čekanju.", show_alert=True)
            await query.edit_message_reply_markup(None)
            return

        if op == "reject":
            self.queue.reject(action_id)
            await query.answer("Odbijeno.")
            await query.edit_message_text(
                ui.action_card(action) + "\n\n❌ <b>Odbijeno</b>", parse_mode=ParseMode.HTML
            )
        elif op == "edit":
            context.user_data["editing"] = action_id
            await query.answer()
            await query.message.reply_text(f"✏️ Pošalji mi novi tekst za nacrt #{action_id} (ili bilo koju /komandu za otkazivanje).")
        elif op == "send":
            if self.queue.is_paused():
                await query.answer("⏸ Pauzirano. Pošalji /nastavi pa pritisni ponovo.", show_alert=True)
                return
            self.queue.approve(action_id)
            result = await self.executor.execute(action_id)
            status = "📤 <b>Poslato</b>" if result.ok else f"⚠️ <b>Nije poslato</b> ({result.reason})"
            await query.answer("Poslato." if result.ok else "Greška.")
            await query.edit_message_text(ui.action_card(action) + f"\n\n{status}", parse_mode=ParseMode.HTML)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("Unhandled error", exc_info=context.error)
