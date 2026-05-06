import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from bot.commands import CommandProcessor
from bot.formatting import split_long_message
from bot.menu import (
    build_main_menu, build_task_list_keyboard, build_task_detail_keyboard,
    handle_menu_callbacks, handle_edit_input, format_task_list
)
from db.repository import Repository

logger = logging.getLogger(__name__)


class BotHandlers:
    def __init__(self, repo: Repository, allowed_user_id: int,
                 out_queue, cli_queue, job_queue=None,
                 speech_service=None, vision_service=None,
                 nl_parser=None, calendar_service=None):
        self.processor = CommandProcessor(repo, allowed_user_id)
        self.allowed_user_id = allowed_user_id
        self.out_queue = out_queue
        self.cli_queue = cli_queue
        self.job_queue = job_queue
        self.speech = speech_service
        self.vision = vision_service
        self.nl = nl_parser
        self.calendar = calendar_service
        self._pending_intents = {}  # user_id -> parsed dict awaiting confirmation
        self._edit_state = {}      # user_id -> edit state dict
        self._voice_mode = {}      # user_id -> bool: озвучивать ответы голосом

    def is_allowed(self, user_id: int) -> bool:
        return user_id == self.allowed_user_id

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        # First clear any stuck ReplyKeyboardMarkup from old bot versions
        await update.message.reply_text(
            "Обновлено",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text(
            "<b>Джарвис к вашим услугам</b>",
            reply_markup=build_main_menu(),
            parse_mode="HTML"
        )

    async def handle_menu_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        await update.message.reply_text(
            "<b>Меню</b>",
            reply_markup=build_main_menu(),
            parse_mode="HTML"
        )

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route all menu-related inline keyboard callbacks."""
        await handle_menu_callbacks(self, update, context)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        text = await self.processor.help()
        await self._respond(update, text)

    async def handle_voice_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        user_id = update.effective_user.id
        self._voice_mode[user_id] = True
        await update.message.reply_text("Голосовой режим включён. Ответы будут озвучиваться.")

    async def handle_voice_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        user_id = update.effective_user.id
        self._voice_mode[user_id] = False
        await update.message.reply_text("Голосовой режим выключен. Ответы будут текстом.")

    async def handle_task_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.task_add(args)
        await self._respond(update, text)

    async def handle_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        tasks = await self.processor.repo.list_tasks(limit=50)
        text = format_task_list(tasks, "Все задачи")
        await update.message.reply_text(
            text,
            reply_markup=build_task_list_keyboard(tasks, "all"),
            parse_mode="HTML"
        )

    async def handle_task_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.task_done(args)
        await self._respond(update, text)

    async def handle_task_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.task_edit(args)
        await self._respond(update, text)

    async def handle_project_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.project_add(args)
        await self._respond(update, text)

    async def handle_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.projects(args)
        await self._respond(update, text)

    async def handle_remind(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text, reminder = await self.processor.remind(args)
        # Schedule in JobQueue for immediate firing
        if reminder and self.job_queue:
            self._schedule_reminder_job(reminder)
        await self._respond(update, text)

    async def handle_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.reminders(args)
        await self._respond(update, text)

    async def handle_remind_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.remind_del(args)
        await self._respond(update, text)

    async def handle_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.note(args)
        await self._respond(update, text)

    async def handle_notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        args = update.message.text.split(maxsplit=1)[1] if len(update.message.text.split()) > 1 else ""
        text = await self.processor.notes(args)
        await self._respond(update, text)

    async def handle_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        text = await self.processor.summary()
        await self._respond(update, text)

    async def handle_overdue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        text = await self.processor.overdue()
        await self._respond(update, text)

    async def handle_overdue_reschedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard actions for overdue task rescheduling."""
        from datetime import datetime, timedelta

        query = update.callback_query
        user_id = update.effective_user.id

        if not self.is_allowed(user_id):
            await query.answer("Нет доступа")
            return

        data = query.data  # e.g. "overdue_tomorrow_42"
        try:
            _, action, task_id_str = data.split("_", 2)
            task_id = int(task_id_str)
        except (ValueError, IndexError):
            await query.answer("Неверные данные")
            return

        task = await self.processor.repo.get_task(task_id)
        if not task:
            await query.answer("Задача не найдена")
            return

        original_text = query.message.text_html or query.message.text
        now = datetime.now()
        if action == "tomorrow":
            new_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            await self.processor.repo.update_task_due_date(task_id, new_date)
            await query.edit_message_text(
                f"{original_text}\n\n✅ Перенесено на завтра ({new_date})",
                parse_mode="HTML"
            )
        elif action == "week":
            new_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
            await self.processor.repo.update_task_due_date(task_id, new_date)
            await query.edit_message_text(
                f"{original_text}\n\n✅ Перенесено на неделю ({new_date})",
                parse_mode="HTML"
            )
        elif action == "cancel":
            await self.processor.repo.cancel_task(task_id)
            await query.edit_message_text(
                f"{original_text}\n\n❌ Задача отменена",
                parse_mode="HTML"
            )
        else:
            await query.answer("Неизвестное действие")
            return

        await query.answer()

    async def handle_free_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_allowed(update.effective_user.id):
            return
        msg = update.message.text.strip()
        if not msg or msg.startswith("/"):
            return

        # Check if user is in edit mode
        if self._edit_state.get(update.effective_user.id):
            await handle_edit_input(self, update, context)
            return

        # Parse the message through LLM
        if self.nl:
            try:
                parsed = await self.nl.parse(msg)
            except Exception as e:
                logger.error(f"LLM parse failed: {e}")
                await self._respond(update, f"Записал: {msg[:150]}")
                return
        else:
            await self._respond(update, f"Записал: {msg[:150]}")
            return

        # Save to memory
        try:
            await self.processor.repo.create_note(content=msg, title=msg[:50])
            await self.processor.repo.save_message("in", msg, "telegram")
        except Exception as e:
            logger.error(f"Failed to save: {e}")

        if self._has_actions(parsed):
            # Store pending intents and show confirmation buttons
            user_id = update.effective_user.id
            self._pending_intents[user_id] = parsed

            confirm_msg = self._build_confirm_message(parsed)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("OK", callback_data="confirm_ok"),
                    InlineKeyboardButton("Нет", callback_data="confirm_no"),
                ]
            ])
            await update.message.reply_text(confirm_msg, reply_markup=keyboard, parse_mode="HTML")
            return

        # No actions — just query or notes: execute immediately
        query_data = await self._execute_intents(parsed)
        reply = parsed.get("reply", "")
        if query_data:
            reply = reply + "\n\n" + query_data if reply else query_data
        if reply:
            await self._respond(update, reply)

    async def handle_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle OK/Нет button press for intent confirmation."""
        query = update.callback_query
        user_id = update.effective_user.id

        if not self.is_allowed(user_id):
            await query.answer("Нет доступа")
            return

        action = query.data
        parsed = self._pending_intents.pop(user_id, None)

        if action == "confirm_ok":
            if parsed is None:
                await query.edit_message_text("Нечего выполнять (данные устарели)")
                return

            await query.edit_message_text("Выполняю...")

            # Execute all intents
            query_data = await self._execute_intents(parsed)

            # Build result
            reply = parsed.get("reply", "Готово!")
            if query_data:
                reply = reply + "\n\n" + query_data if reply else query_data
            await query.edit_message_text(reply, parse_mode="HTML")

            # Also send via out_queue
            await self.out_queue.put({"text": reply, "source": "jarvis"})
            await self.processor.repo.save_message("out", reply, "jarvis")

        elif action == "confirm_no":
            await query.edit_message_text("Пришлите новый промпт")
            await self.out_queue.put({"text": "Действие отменено пользователем", "source": "system"})

        await query.answer()

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages: transcribe with Whisper, then process as text."""
        if not self.is_allowed(update.effective_user.id):
            return

        # Check if in thought-adding mode
        user_id = update.effective_user.id
        state = self._edit_state.get(user_id)
        if state and state.get("field") == "new_thought":
            await self._handle_thought_voice(update, context)
            return

        if not self.speech:
            await update.message.reply_text("Распознавание аудио не настроено")
            return

        await update.message.reply_text("Распознаю речь...")
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        import tempfile, os
        ogg_path = os.path.join(tempfile.gettempdir(), f"voice_{voice.file_id}.ogg")
        await file.download_to_drive(ogg_path)

        text = await self.speech.transcribe(ogg_path)
        os.unlink(ogg_path)

        if text:
            await update.message.reply_text(f"Распознано: {text}")
            await self.out_queue.put({"text": f"[Voice] {text}", "source": "telegram"})

            # Process through same confirmation-aware flow as text
            if self.nl:
                try:
                    parsed = await self.nl.parse(text)
                except Exception as e:
                    logger.error(f"LLM parse failed: {e}")
                    await self._reply_or_voice(update, f"Записал: {text[:150]}")
                    return
            else:
                await self._reply_or_voice(update, f"Записал: {text[:150]}")
                return

            # Save to memory
            try:
                await self.processor.repo.create_note(content=text, title=text[:50])
                await self.processor.repo.save_message("in", text, "telegram")
            except Exception as e:
                logger.error(f"Failed to save: {e}")

            if self._has_actions(parsed):
                user_id = update.effective_user.id
                self._pending_intents[user_id] = parsed
                confirm_msg = self._build_confirm_message(parsed)
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("OK", callback_data="confirm_ok"),
                        InlineKeyboardButton("Нет", callback_data="confirm_no"),
                    ]
                ])
                await update.message.reply_text(confirm_msg, reply_markup=keyboard, parse_mode="HTML")
                return

            query_data = await self._execute_intents(parsed)
            reply = parsed.get("reply", "")
            if query_data:
                reply = reply + "\n\n" + query_data if reply else query_data
            if reply:
                await self._reply_or_voice(update, reply)
        else:
            await update.message.reply_text("Не удалось распознать речь")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photos: describe with DeepSeek Vision, or save as thought."""
        if not self.is_allowed(update.effective_user.id):
            return

        # Check if in thought-adding mode
        user_id = update.effective_user.id
        state = self._edit_state.get(user_id)
        if state and state.get("field") == "new_thought":
            await self._handle_thought_photo(update, context)
            return

        if not self.vision:
            await update.message.reply_text("Распознавание изображений не настроено (нужен DeepSeek API ключ)")
            return

        await update.message.reply_text("Анализирую изображение...")
        photo = update.message.photo[-1]
        caption = update.message.caption or ""

        import tempfile, os
        img_path = os.path.join(tempfile.gettempdir(), f"photo_{photo.file_id}.jpg")
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(img_path)

        prompt = f"Опиши это изображение подробно на русском языке. Контекст от пользователя: {caption}" if caption else None
        description = await self.vision.describe(img_path, prompt)
        os.unlink(img_path)

        await update.message.reply_text(description)
        await self.out_queue.put({"text": f"[Photo] {description[:200]}", "source": "telegram"})
        await self.processor.repo.create_note(
            content=f"[Изображение] {description}", title=description[:50]
        )

    async def _handle_thought_voice(self, update, context):
        """Transcribe voice and save as thought."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        user_id = update.effective_user.id
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        import tempfile, os
        ogg_path = os.path.join(tempfile.gettempdir(), f"thought_voice_{voice.file_id}.ogg")
        await file.download_to_drive(ogg_path)

        text = ""
        if self.speech:
            text = await self.speech.transcribe(ogg_path)
        os.unlink(ogg_path)

        content = text or "[голосовое без расшифровки]"
        thought = await self.processor.repo.create_thought(content=content, kind="voice")
        del self._edit_state[user_id]
        await update.message.reply_text(
            f"🎤 Мысль сохранена: {content[:100]}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ К ленте", callback_data="view_thoughts"),
                InlineKeyboardButton("➕ Ещё", callback_data="new_thought"),
            ]])
        )

    async def _handle_thought_photo(self, update, context):
        """Save photo locally and add to thought feed."""
        from pathlib import Path
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        user_id = update.effective_user.id

        # Ensure images directory exists
        img_dir = Path(__file__).parent.parent / "thoughts_images"
        img_dir.mkdir(exist_ok=True)

        photo = update.message.photo[-1]
        caption = update.message.caption or ""

        # Download photo
        file = await context.bot.get_file(photo.file_id)
        timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"thought_{timestamp}_{photo.file_id}.jpg"
        img_path = img_dir / filename
        await file.download_to_drive(str(img_path))

        thought = await self.processor.repo.create_thought(
            content=caption or "[фото]", kind="image", image_path=str(img_path)
        )
        del self._edit_state[user_id]
        await update.message.reply_text(
            "🖼 Фото сохранено в ленту мыслей",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ К ленте", callback_data="view_thoughts"),
                InlineKeyboardButton("➕ Ещё", callback_data="new_thought"),
            ]])
        )

    def _schedule_reminder_job(self, reminder: dict):
        """Schedule a reminder in PTB's JobQueue."""
        from datetime import datetime
        trigger_at = datetime.fromisoformat(reminder["trigger_at"])
        now = datetime.now()
        delta = (trigger_at - now).total_seconds()
        if delta > 0:
            self.job_queue.run_once(
                self._fire_reminder,
                when=delta,
                data={"reminder_id": reminder["id"], "message": reminder["message"]},
                name=f"reminder_{reminder['id']}"
            )
            logger.info(f"Scheduled reminder #{reminder['id']} in {delta:.0f}s at {reminder['trigger_at']}")

    async def _fire_reminder(self, context):
        """Fire a reminder: send to Telegram + CLI."""
        data = context.job.data
        text = f"⏰ Напоминание: {data['message']}"
        await context.bot.send_message(chat_id=self.allowed_user_id, text=text)
        await self.out_queue.put({"text": text, "source": "system"})
        await self.processor.repo.mark_reminder_sent(data["reminder_id"])

    async def _has_actions(self, parsed: dict) -> bool:
        """Check if parsed result contains actionable intents (not just query/notes)."""
        return bool(parsed.get("events") or parsed.get("tasks") or parsed.get("reminders"))

    def _build_confirm_message(self, parsed: dict) -> str:
        """Build a human-readable summary of what the LLM wants to do."""
        reply = parsed.get("reply", "")
        lines = [reply] if reply else ["<b>Я собираюсь:</b>"]

        for ev in parsed.get("events", []):
            lines.append(f"  Событие: {ev.get('summary', '?')} в {ev.get('start', '?')}")
        for t in parsed.get("tasks", []):
            due = f" к {t['due_date']}" if t.get("due_date") else ""
            lines.append(f"  Задача: {t.get('title', '?')}{due}")
        for r in parsed.get("reminders", []):
            lines.append(f"  Напоминание: {r.get('message', '?')} в {r.get('when', '?')}")

        lines.append("\n<b>Ок?</b>")
        return "\n".join(lines)

    async def _parse_free_text(self, msg: str) -> str | None:
        """LLM-based NL parser: DeepSeek understands the message, we execute intents.
        Returns text response OR None if confirmation buttons were sent."""

        # Always save original message for memory
        try:
            await self.processor.repo.create_note(content=msg, title=msg[:50])
            await self.processor.repo.save_message("in", msg, "telegram")
        except Exception as e:
            logger.error(f"Failed to save: {e}")

        # Use LLM to parse the message
        if self.nl:
            try:
                parsed = await self.nl.parse(msg)
            except Exception as e:
                logger.error(f"LLM parse failed: {e}")
                return f"Записал: {msg[:150]}"

            # If there are actionable intents, request confirmation first
            if self._has_actions(parsed):
                return None  # caller will handle confirmation flow

            # No actions — just a query or notes: execute and return
            query_data = await self._execute_intents(parsed)
            reply = parsed.get("reply", "")
            if query_data:
                reply = reply + "\n\n" + query_data if reply else query_data
            if reply:
                return reply

        # Fallback: save as note
        return f"Записал: {msg[:150]}"

    async def _execute_intents(self, parsed: dict) -> str | None:
        """Execute calendar events, tasks, reminders from LLM response.
        Returns query_result string if user asked a question about existing data."""
        from datetime import datetime

        # Create calendar events
        for event_data in parsed.get("events", []):
            try:
                summary = event_data.get("summary", "Событие")
                start_str = event_data.get("start", "")
                end_str = event_data.get("end") or ""
                description = event_data.get("description", "")
                reminder_mins = event_data.get("reminder_minutes", [])

                if not start_str:
                    continue

                start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M") if end_str else None

                reminders = [{"method": "popup", "minutes": m} for m in reminder_mins] if reminder_mins else None

                if self.calendar:
                    await self.calendar.create_event(
                        summary=summary,
                        start_time=start_dt,
                        end_time=end_dt,
                        description=description,
                        reminders=reminders,
                    )
                    logger.info(f"Calendar event created: {summary}")
                else:
                    # Fallback to DB task
                    await self.processor.repo.create_task(
                        title=summary,
                        due_date=start_dt.strftime("%Y-%m-%d"),
                        priority=1,
                        tags="event"
                    )

            except Exception as e:
                logger.error(f"Failed to create event: {e}")

        # Create DB tasks
        project_id = parsed.get("_project_id")
        for task_data in parsed.get("tasks", []):
            try:
                title = task_data.get("title", "Задача")
                due = task_data.get("due_date") or None
                priority = task_data.get("priority", 0)
                tags = task_data.get("tags", "")
                pid = task_data.get("project_id") or project_id

                await self.processor.repo.create_task(
                    title=title,
                    due_date=due,
                    priority=priority,
                    tags=tags,
                    project_id=pid
                )
                logger.info(f"Task created: {title}")
            except Exception as e:
                logger.error(f"Failed to create task: {e}")

        # Create reminders
        for rem_data in parsed.get("reminders", []):
            try:
                message = rem_data.get("message", "Напоминание")
                when = rem_data.get("when", "")
                if when:
                    reminder = await self.processor.repo.create_reminder(
                        message=message,
                        trigger_at=when
                    )
                    if self.job_queue:
                        self._schedule_reminder_job(reminder)
                    logger.info(f"Reminder created: {message}")
            except Exception as e:
                logger.error(f"Failed to create reminder: {e}")

        # Save notes
        for note_text in parsed.get("notes", []):
            try:
                await self.processor.repo.create_note(content=note_text, title=note_text[:50])
            except Exception as e:
                logger.error(f"Failed to save note: {e}")

        # Handle query (questions about existing data)
        query = parsed.get("query")
        if query:
            logger.info(f"User query: {query}")
            return await self._fetch_query_data(query)

        return None

    async def _fetch_query_data(self, query: str) -> str | None:
        """Fetch data relevant to user's question from DB."""
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        lines = []
        s = {"todo": "[ ]", "in_progress": "[>]", "done": "[x]", "blocked": "[!]", "cancelled": "[-]"}

        # Fetch today's and tomorrow's tasks
        try:
            all_tasks = await self.processor.repo.list_tasks(limit=50)
            today_tasks = [t for t in all_tasks if (t.get("due_date") or "").startswith(today)]
            tomorrow_tasks = [t for t in all_tasks if (t.get("due_date") or "").startswith(tomorrow)]

            if today_tasks:
                lines.append(f"<b>На сегодня ({today}):</b>")
                for t in today_tasks:
                    lines.append(f"  {s.get(t['status'], '?')} {t['title']}")

            if tomorrow_tasks:
                lines.append(f"<b>На завтра ({tomorrow}):</b>")
                for t in tomorrow_tasks:
                    lines.append(f"  {s.get(t['status'], '?')} {t['title']}")

            if not today_tasks and not tomorrow_tasks:
                # Try all tasks
                if all_tasks:
                    lines.append("<b>Все задачи:</b>")
                    for t in all_tasks[:15]:
                        due = t.get("due_date") or "—"
                        lines.append(f"  {s.get(t['status'], '?')} {t['title']} (due: {due})")
        except Exception as e:
            logger.error(f"Failed to fetch tasks for query: {e}")

        # Fetch upcoming reminders
        try:
            reminders = await self.processor.repo.get_upcoming_reminders()
            if reminders:
                lines.append(f"\n<b>Ближайшие напоминания:</b>")
                for r in reminders[:5]:
                    lines.append(f"  {r['message']} ({r['trigger_at']})")
        except Exception as e:
            logger.error(f"Failed to fetch reminders for query: {e}")

        return "\n".join(lines) if lines else None

    async def _respond(self, update: Update, text: str):
        """Send response to both Telegram and CLI queue."""
        parts = split_long_message(text)
        for part in parts:
            await update.message.reply_text(part, parse_mode="HTML")
            await self.out_queue.put({"text": part, "source": "jarvis"})
            await self.processor.repo.save_message("out", part, "jarvis")

    async def _reply_or_voice(self, update: Update, text: str):
        """Send text or voice response depending on voice_mode setting."""
        user_id = update.effective_user.id
        if self._voice_mode.get(user_id) and self.speech:
            try:
                ogg_path = await self.speech.synthesize(text)
                with open(ogg_path, "rb") as f:
                    await update.message.reply_voice(f, caption=text[:200])
                os.unlink(ogg_path)
                await self.out_queue.put({"text": text, "source": "jarvis"})
                await self.processor.repo.save_message("out", text, "jarvis")
            except Exception as e:
                logger.error(f"TTS failed, falling back to text: {e}")
                await self._respond(update, text)
        else:
            await self._respond(update, text)

    def register(self, app):
        """Register all handlers on the PTB Application."""
        app.add_handler(CommandHandler("start", self.handle_start))
        app.add_handler(CommandHandler("menu", self.handle_menu_cmd))
        app.add_handler(CommandHandler("help", self.handle_help))
        app.add_handler(CommandHandler("task_add", self.handle_task_add))
        app.add_handler(CommandHandler("tasks", self.handle_tasks))
        app.add_handler(CommandHandler("task_done", self.handle_task_done))
        app.add_handler(CommandHandler("task_edit", self.handle_task_edit))
        app.add_handler(CommandHandler("project_add", self.handle_project_add))
        app.add_handler(CommandHandler("projects", self.handle_projects))
        app.add_handler(CommandHandler("remind", self.handle_remind))
        app.add_handler(CommandHandler("reminders", self.handle_reminders))
        app.add_handler(CommandHandler("remind_del", self.handle_remind_del))
        app.add_handler(CommandHandler("note", self.handle_note))
        app.add_handler(CommandHandler("notes", self.handle_notes))
        app.add_handler(CommandHandler("summary", self.handle_summary))
        app.add_handler(CommandHandler("overdue", self.handle_overdue))
        app.add_handler(CommandHandler("voice_on", self.handle_voice_on))
        app.add_handler(CommandHandler("voice_off", self.handle_voice_off))
        # Voice and photo handlers
        app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        # Free text handler (must be last)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_free_text))
        # Inline button callbacks
        app.add_handler(CallbackQueryHandler(self.handle_confirmation, pattern="^confirm_"))
        app.add_handler(CallbackQueryHandler(self.handle_overdue_reschedule, pattern="^overdue_"))
        app.add_handler(CallbackQueryHandler(self.handle_menu, pattern="^(menu|view_|detail_|complete_|delete_|postpone_|edit_|new_|project_|proj_|hoursel_|minsel_|rollover_|thought_)"))
