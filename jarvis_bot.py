import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from telegram.ext import Application

from config import load_config
from db.database import Database
from db.repository import Repository
from bot.handlers import BotHandlers
from cli.console import ConsoleBridge
from services.reminder_service import ReminderService
from services.proactive import ProactiveService
from services.speech import SpeechService
from services.vision import VisionService
from services.nl_parser import NLParser
from services.calendar_service import CalendarService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("jarvis.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("jarvis")


async def schedule_pending_reminders(app: Application, repo: Repository, out_queue):
    """On startup, schedule all pending reminders using PTB's JobQueue."""
    pending = await repo.get_pending_reminders()
    now = datetime.now()
    scheduled = 0
    missed = 0

    for reminder in pending:
        trigger_time = datetime.fromisoformat(reminder["trigger_at"])
        if trigger_time > now:
            # Future reminder - schedule it
            delta_seconds = (trigger_time - now).total_seconds()
            app.job_queue.run_once(
                fire_reminder_callback,
                when=delta_seconds,
                data={"reminder_id": reminder["id"], "message": reminder["message"]},
                name=f"reminder_{reminder['id']}"
            )
            scheduled += 1
        else:
            # Missed reminder - fire immediately
            text = f"⚠️ Пропущенное напоминание: {reminder['message']} (было {reminder['trigger_at']})"
            await out_queue.put({"text": text, "source": "system"})
            await repo.mark_reminder_sent(reminder["id"])
            missed += 1

    if scheduled or missed:
        logger.info(f"Reminders loaded: {scheduled} scheduled, {missed} missed")


async def fire_reminder_callback(context):
    """Callback fired by PTB JobQueue when a reminder is due."""
    data = context.job.data
    text = f"⏰ Напоминание: {data['message']}"

    # Access bot and repo through application context
    app = context.application
    out_queue = app.bot_data.get("out_queue")
    repo = app.bot_data.get("repo")

    if out_queue:
        await out_queue.put({"text": text, "source": "system"})

    # Send to Telegram
    await context.bot.send_message(
        chat_id=app.bot_data["user_id"],
        text=text
    )

    if repo:
        await repo.mark_reminder_sent(data["reminder_id"])

        # Handle repeating reminders
        reminder = await repo.get_reminder(data["reminder_id"])
        if reminder and reminder.get("repeat_interval", "none") != "none":
            reminder_service = ReminderService(repo)
            await reminder_service.reschedule_repeating(reminder)


async def handle_cli_input(cli_queue, processor, out_queue, repo, bot, user_id):
    """Process messages from CLI queue."""
    while True:
        msg = await cli_queue.get()
        text = msg.get("text", "").strip()
        if not text:
            continue

        # Save message to DB
        await repo.save_message("in", text, "cli")

        # Route to command processor based on text
        response = None
        if text.startswith("/"):
            cmd_parts = text[1:].split(maxsplit=1)
            cmd = cmd_parts[0]
            args = cmd_parts[1] if len(cmd_parts) > 1 else ""

            cmd_map = {
                "start": processor.start,
                "help": processor.help,
                "task_add": lambda: processor.task_add(args),
                "tasks": lambda: processor.tasks(args),
                "task_done": lambda: processor.task_done(args),
                "task_edit": lambda: processor.task_edit(args),
                "project_add": lambda: processor.project_add(args),
                "projects": lambda: processor.projects(args),
                "remind": lambda: processor.remind(args)[0],
                "reminders": lambda: processor.reminders(args),
                "remind_del": lambda: processor.remind_del(args),
                "note": lambda: processor.note(args),
                "notes": lambda: processor.notes(args),
                "summary": processor.summary,
                "overdue": processor.overdue,
            }
            handler = cmd_map.get(cmd)
            if handler:
                response = await handler()
            else:
                response = f"Неизвестная команда: {cmd}. /help для списка команд"
        else:
            # Free text from CLI - treat as note
            response = f"Сохранил заметку: {text[:100]}"
            await repo.create_note(content=text, title=text[:50])

        if response:
            await out_queue.put({"text": response, "source": "jarvis"})
            await repo.save_message("out", response, "jarvis")
            # Also send to Telegram
            try:
                await bot.send_message(chat_id=user_id, text=response)
            except Exception as e:
                logger.error(f"Failed to send TG message: {e}")


async def main():
    config = load_config()
    logger.info("Starting Jarvis bot...")

    # Database
    db = Database(config["db_path"])
    await db.connect()
    repo = Repository(db)
    logger.info("Database connected")

    # Queues for CLI bridge
    cli_to_bot = asyncio.Queue()
    bot_to_cli = asyncio.Queue()

    # PTB Application
    app = Application.builder().token(config["bot_token"]).build()

    # Store shared objects in bot_data for callback access
    app.bot_data["out_queue"] = bot_to_cli
    app.bot_data["repo"] = repo
    app.bot_data["user_id"] = config["allowed_user_id"]

    # Initialize services
    speech_service = SpeechService(model_name="tiny")  # Whisper tiny model for fast CPU inference
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    vision_service = VisionService(deepseek_key) if deepseek_key else None
    nl_parser = NLParser(deepseek_key) if deepseek_key else None
    calendar_service = CalendarService()

    # Register handlers
    handlers = BotHandlers(repo, config["allowed_user_id"], bot_to_cli, cli_to_bot,
                           app.job_queue, speech_service, vision_service,
                           nl_parser, calendar_service)
    handlers.register(app)

    # Global error handler
    async def error_handler(update, context):
        logger.error(f"Error processing update: {context.error}", exc_info=context.error)
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка. Попробуй ещё раз."
            )

    app.add_error_handler(error_handler)

    # Schedule pending reminders on startup
    await app.initialize()
    await app.start()
    await schedule_pending_reminders(app, repo, bot_to_cli)

    # Start proactive services (morning/evening briefings, overdue checks)
    proactive = ProactiveService(app.job_queue, repo, bot_to_cli, None)
    proactive.schedule_all(config["allowed_user_id"])

    # Midnight rollover: move unfinished tasks from yesterday to today
    async def midnight_rollover(context):
        db_repo = context.application.bot_data["repo"]
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        # Find yesterday's tasks that aren't done/cancelled
        tasks = await db_repo.list_tasks(limit=200)
        rolled = 0
        for t in tasks:
            due = t.get("due_date") or ""
            if due.startswith(yesterday) and t["status"] not in ("done", "cancelled"):
                new_due = today + due[len(yesterday):]  # preserve time part if any
                await db_repo.update_task(t["id"], due_date=new_due)
                rolled += 1
        if rolled:
            logger.info(f"Midnight rollover: {rolled} tasks moved from {yesterday} to {today}")

    app.job_queue.run_daily(
        midnight_rollover,
        time=time(hour=0, minute=5),
        days=(0, 1, 2, 3, 4, 5, 6),
        name="midnight_rollover"
    )
    logger.info("Midnight rollover scheduled daily at 00:05")

    # Daily gangster affirmation (random wisdom via DeepSeek, fresh each day)
    if deepseek_key:
        from services.affirmation import AffirmationService
        affirmation_svc = AffirmationService(deepseek_key)

        async def daily_affirmation(context):
            text = await affirmation_svc.generate()
            if text:
                user_id = context.application.bot_data["user_id"]
                await context.bot.send_message(chat_id=user_id, text=f"🧠 {text}")
                logger.info(f"Daily affirmation sent")

                # Update README.md with the new wisdom
                readme_path = Path(__file__).parent / "README.md"
                try:
                    lines = readme_path.read_text(encoding="utf-8").splitlines()
                    new_lines = []
                    for line in lines:
                        if line.startswith("> **«") and line.endswith("».**"):
                            new_lines.append(f"> **«{text}».**")
                        else:
                            new_lines.append(line)
                    readme_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

                    # Commit and push
                    import subprocess
                    subprocess.run(["git", "add", "README.md"], cwd=str(readme_path.parent), capture_output=True)
                    subprocess.run(
                        ["git", "commit", "-m", f"Daily wisdom: {text[:50]}" + ("..." if len(text) > 50 else "")],
                        cwd=str(readme_path.parent), capture_output=True
                    )
                    subprocess.run(["git", "push"], cwd=str(readme_path.parent), capture_output=True)
                    logger.info(f"README updated with daily wisdom")
                except Exception as e:
                    logger.error(f"Failed to update README with wisdom: {e}")

        app.job_queue.run_daily(
            daily_affirmation,
            time=time(hour=9, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="daily_affirmation"
        )
        logger.info("Daily affirmation scheduled at 09:00")

    # Start 2-agent self-improvement system (every 2 days + weekly review)
    if deepseek_key:
        from services.idea_orchestrator import IdeaOrchestrator

        orchestrator = IdeaOrchestrator(
            deepseek_key, str(Path(__file__).parent), repo,
            bot_to_cli, config["allowed_user_id"]
        )
        app.bot_data["orchestrator"] = orchestrator

        async def biweekly_cycle(context):
            await orchestrator.run_cycle()

        async def weekly_review(context):
            await orchestrator.run_weekly_review()

        # Check daily at 11:00 — orchestrator decides if 2 days passed
        app.job_queue.run_daily(
            biweekly_cycle,
            time=time(hour=11, minute=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="idea_cycle"
        )
        logger.info("IdeaOrchestrator cycle check scheduled daily at 11:00")

        # Weekly global review on Monday at 10:00
        app.job_queue.run_daily(
            weekly_review,
            time=time(hour=10, minute=0),
            days=(0,),  # Monday
            name="weekly_review"
        )
        logger.info("IdeaOrchestrator weekly review scheduled on Mondays at 10:00")

    # Start polling
    await app.updater.start_polling()
    logger.info("Bot polling started. Waiting for messages...")

    # Build output announcer
    async def announce_startup():
        await bot_to_cli.put({
            "text": "Jarvis запущен. Жду сообщений...",
            "source": "system"
        })

    await announce_startup()

    # CLI bridge
    console = ConsoleBridge(cli_to_bot, bot_to_cli)

    # Run everything concurrently
    loop = asyncio.get_event_loop()

    # Handle graceful shutdown
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutting down...")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)
    except (NotImplementedError, RuntimeError):
        # Windows doesn't support add_signal_handler
        if sys.platform == "win32":
            signal.signal(signal.SIGINT, lambda s, f: shutdown())

    # Start CLI reader thread
    await console.start_stdin_reader()

    async with app:
        await asyncio.gather(
            console.stdout_writer(),
            handle_cli_input(cli_to_bot, handlers.processor, bot_to_cli, repo, app.bot, config["allowed_user_id"]),
            stop_event.wait()
        )

    await console.stop()
    await app.updater.stop()
    await app.stop()
    await db.close()
    logger.info("Jarvis stopped")


if __name__ == "__main__":
    asyncio.run(main())
