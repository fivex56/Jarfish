"""Idea Orchestrator: coordinates Agent 1 (Generator) and Agent 2 (Developer).

Runs every 2 days:
  1. Generator: analyze + search + brainstorm → saves ideas
  2. Developer: review + critique → saves feedback
  3. Generator: refine with feedback → saves refined ideas
  4. Developer: attempt implementation → commit to git

Runs weekly: global strategic review → report to user."""

import logging
import asyncio
from datetime import datetime
from pathlib import Path

from db.repository import Repository
from services.idea_generator import IdeaGenerator
from services.idea_developer import IdeaDeveloper

logger = logging.getLogger("agent.orchestrator")


class IdeaOrchestrator:
    def __init__(self, deepseek_key: str, project_root: str, repo: Repository,
                 out_queue, user_id: int):
        self.generator = IdeaGenerator(deepseek_key, project_root, repo)
        self.developer = IdeaDeveloper(project_root, repo)
        self.repo = repo
        self.out_queue = out_queue
        self.user_id = user_id
        self.project_root = project_root
        self._last_weekly = None
        self._last_cycle_date = None

    async def run_cycle(self):
        """Run a full 2-day idea cycle. Never hangs — errors at any step are caught and reported."""
        today = datetime.now().strftime("%Y-%m-%d")

        if self._last_cycle_date == today:
            logger.info("Cycle already ran today, skipping")
            return

        if self._last_cycle_date:
            last = datetime.strptime(self._last_cycle_date, "%Y-%m-%d")
            delta = (datetime.now() - last).days
            if delta < 2:
                logger.info(f"Last cycle was {delta} days ago, skipping (need 2+ days)")
                return

        self._last_cycle_date = today
        logger.info("=== Agent cycle started ===")

        try:
            await self._run_steps()
        except Exception as e:
            logger.error(f"Cycle crashed: {e}", exc_info=True)
            try:
                await self._notify(f"⚠️ Цикл саморазвития упал с ошибкой: {str(e)[:300]}\nСледующая попытка через 2 дня.")
            except Exception:
                pass

    async def _run_steps(self):

        # --- Step 1: Generator analyses & brainstorms ---
        await self._notify("🧠 Агент-Генератор начал анализ проекта и поиск идей...")
        logger.info("Step 1: Generator analysing project")

        project_info = await self.generator.analyze_project()
        logger.info("Step 1: Searching web trends")
        trends = await self.generator.search_trends()
        logger.info("Step 1: Brainstorming ideas via DeepSeek")
        generation = await self.generator.brainstorm(project_info, trends)

        ideas = generation.get("ideas", [])
        summary = generation.get("summary", "Идей нет")

        # Save generator's ideas to DB
        for idea in ideas:
            await self.repo.create_idea(
                content=f"{idea.get('title', '')}: {idea.get('what', '')}",
                round="generation",
                agent="generator",
                status="pending"
            )

        # Save ideas to file for pending approval
        if ideas:
            import json as _json
            pending_path = Path(self.project_root) / ".pending_ideas.json"
            _json.dump(ideas, pending_path.open("w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)

            # Numbered list for user to pick from
            numbered = "\n".join(
                f"{idx}. {i.get('title', '?')} — {i.get('what', '?')[:100]} "
                f"({i.get('impact', '?')} impact, {i.get('effort', '?')} effort)"
                for idx, i in enumerate(ideas, 1)
            )
            await self._notify(
                f"💡 Генератор придумал {len(ideas)} идей:\n\n"
                f"{numbered}\n\n"
                f"_{summary}_\n\n"
                f"⬇️ <b>ОТВЕТЬ НОМЕРАМИ</b> какие берём в работу:\n"
                f"<code>1 3 5</code> — значит берём идеи 1, 3 и 5\n"
                f"Остальные отбрасываем.",
                parse_mode="HTML"
            )
            # Stop here — wait for user approval
            return
        else:
            await self._notify(
                f"⚠️ Генератор не смог придумать структурированных идей.\n"
                f"Ответ ИИ: {summary[:400]}\n\n"
                f"Цикл прерван — следующая попытка через 2 дня."
            )
            return

        # --- Step 2: Developer reviews ---
        await self._notify("🔍 Агент-Разработчик проверяет логи и анализирует идеи...")
        logger.info("Step 2: Developer reviewing ideas")

        log_analysis = await self.developer.analyze_logs()
        project_state = await self.developer.analyze_project_state()
        review = await self.developer.review(ideas, log_analysis, project_state)

        reviews = review.get("reviews", [])
        log_insights = review.get("log_insights", "")
        arch_notes = review.get("architecture_notes", "")
        review_summary = review.get("summary", "")

        # Save reviews to DB (as children of generation ideas)
        for i, rev in enumerate(reviews):
            parent_id = None
            if i < len(ideas):
                # Find the DB record for this idea
                recent = await self.repo.list_ideas(round="generation", status="pending", limit=10)
                if recent and i < len(recent):
                    parent_id = recent[-(i + 1)]["id"]

            await self.repo.create_idea(
                content=f"Verdict: {rev.get('verdict', '?')}. {rev.get('feedback', '')}",
                round="review",
                agent="developer",
                parent_id=parent_id,
                status="completed"
            )

        # Show review results
        approved = [r for r in reviews if r.get("verdict") == "approved"]
        rejected = [r for r in reviews if r.get("verdict") == "rejected"]
        needs_work = [r for r in reviews if r.get("verdict") == "needs_revision"]

        review_msg = (
            f"📊 Разработчик проверил идеи:\n"
            f"✅ Одобрено: {len(approved)}\n"
            f"🔧 Нужна доработка: {len(needs_work)}\n"
            f"❌ Отклонено: {len(rejected)}\n"
        )
        if log_insights:
            review_msg += f"\n📋 Из логов: {log_insights[:300]}"
        if arch_notes:
            review_msg += f"\n🏗 По архитектуре: {arch_notes[:300]}"

        await self._notify(review_msg)

        # --- Step 3: Generator refines with feedback ---
        if needs_work:
            await self._notify("🔄 Генератор дорабатывает идеи с учётом замечаний...")
            logger.info("Step 3: Generator refining ideas")

            feedback_text = "\n".join(
                f"Идея: {r.get('idea_title', '')}\n"
                f"Вердикт: {r.get('verdict', '')}\n"
                f"Фидбек: {r.get('feedback', '')}"
                for r in reviews
            )

            refined = await self.generator.brainstorm(
                project_info, trends, previous_feedback=feedback_text
            )
            refined_ideas = refined.get("ideas", [])
            refined_summary = refined.get("summary", "")

            for idea in refined_ideas:
                await self.repo.create_idea(
                    content=f"{idea.get('title', '')}: {idea.get('what', '')}",
                    round="refinement",
                    agent="generator",
                    status="pending"
                )

            await self._notify(
                f"✨ Генератор доработал идеи. Теперь {len(refined_ideas)} предложений.\n\n"
                f"_{refined_summary}_"
            )

            # Match approved reviews back to original ideas for implementation
            approved_ideas = []
            for r in approved:
                review_title = r.get("idea_title", "").strip().lower()
                for idea in ideas:
                    if idea.get("title", "").strip().lower() == review_title:
                        approved_ideas.append(idea)
                        break

            all_approved = approved_ideas + refined_ideas
        else:
            # Match approved reviews back to original ideas
            approved_ideas = []
            for r in approved:
                review_title = r.get("idea_title", "").strip().lower()
                for idea in ideas:
                    if idea.get("title", "").strip().lower() == review_title:
                        approved_ideas.append(idea)
                        break

            all_approved = approved_ideas

        # --- Step 4: Developer attempts implementation ---
        # Take all approved ideas, heavy ones go to weekly review, low+medium get implemented now
        effort_order = {"low": 0, "medium": 1, "high": 99}
        impact_order = {"high": 0, "medium": 1, "low": 2}

        # Split: implement low+medium now, save heavy for weekly review
        for_impl = [i for i in all_approved if isinstance(i, dict) and i.get("effort") != "high"]
        for_weekly = [i for i in all_approved if isinstance(i, dict) and i.get("effort") == "high"]

        if for_weekly:
            heavy_titles = ", ".join(i.get("title", "?") for i in for_weekly)
            await self._notify(f"📦 Тяжёлые идеи отложены на еженедельный обзор: {heavy_titles}")

        implementable = sorted(
            for_impl,
            key=lambda i: (effort_order.get(i.get("effort", "medium"), 1),
                           impact_order.get(i.get("impact", "low"), 2))
        )

        if implementable:
            await self._notify(f"🔨 Разработчик внедряет {len(implementable[:2])} идей (лёгкие и средние)...")
            logger.info(f"Step 4: Developer implementing {len(implementable[:2])} ideas")

            for idea in implementable[:2]:  # Max 2 per cycle
                await self._notify(f"🔧 Внедряю: {idea.get('title', '?')} (сложность: {idea.get('effort', '?')})...")

                impl_result = await self.developer.implement(idea)

                # Save implementation result
                await self.repo.create_idea(
                    content=f"Implementation result: {impl_result[:500]}",
                    round="implementation",
                    agent="developer",
                    status="completed"
                )

                # Update README changelog with this implementation
                await self._update_readme_changelog(idea)

                # Try to commit if there are actual changes
                try:
                    import subprocess
                    root = Path(self.project_root)
                    subprocess.run(["git", "add", "-A"], cwd=str(root),
                                   capture_output=True, timeout=15)
                    result = subprocess.run(
                        ["git", "diff", "--cached", "--stat"],
                        cwd=str(root), capture_output=True, text=True, timeout=15
                    )
                    if result.stdout.strip():
                        msg = f"Agent-implemented: {idea.get('title', 'improvement')}"
                        subprocess.run(["git", "commit", "-m", msg],
                                       cwd=str(root), capture_output=True, timeout=15)
                        subprocess.run(["git", "push"], cwd=str(root),
                                       capture_output=True, timeout=15)
                        await self._notify(f"✅ Внедрено и залито на гитхаб: {idea.get('title', '?')}")
                    else:
                        await self._notify(f"📝 Для «{idea.get('title', '?')}» сгенерирован план внедрения, лежит в базе идей")
                except Exception as e:
                    logger.warning(f"Git operation failed: {e}")
        else:
            await self._notify("⚠️ Нет идей для немедленного внедрения (все тяжёлые — уйдут в еженедельный обзор)")

        # --- Final cycle report ---
        await self._notify(
            f"🏁 Цикл саморазвития завершён.\n\n"
            f"Сгенерировано идей: {len(ideas)}\n"
            f"Одобрено: {len(approved)}\n"
            f"Отклонено: {len(rejected)}\n"
            f"Попыток внедрения: {len(implementable[:2])}\n\n"
            f"Следующий цикл — через 2 дня."
        )

        logger.info("=== Agent cycle completed ===")

    async def run_weekly_review(self):
        """Run a weekly global strategic review."""
        logger.info("=== Weekly global review started ===")
        await self._notify("🌍 Еженедельный стратегический обзор...")

        project_info = await self.generator.analyze_project()
        all_ideas = await self.repo.list_ideas(limit=100)
        review = await self.generator.global_review(project_info, all_ideas)

        vision = review.get("vision", "")
        weaknesses = review.get("weaknesses", [])
        opportunities = review.get("opportunities", [])
        big_ideas = review.get("big_ideas", [])
        report = review.get("report", "")

        # Save to DB
        await self.repo.create_idea(
            content=f"WEEKLY REVIEW. Vision: {vision}",
            round="weekly",
            agent="generator",
            status="completed"
        )

        for idea in big_ideas:
            await self.repo.create_idea(
                content=f"{idea.get('title', '')}: {idea.get('what', '')}",
                round="weekly",
                agent="generator",
                status="pending"
            )

        # Build report message
        msg = "🌍 <b>Стратегический обзор недели</b>\n\n"
        if vision:
            msg += f"<b>Видение:</b> {vision}\n\n"
        if weaknesses:
            msg += "<b>Слабые места:</b>\n"
            for w in weaknesses:
                msg += f"• {w}\n"
            msg += "\n"
        if opportunities:
            msg += "<b>Возможности:</b>\n"
            for o in opportunities:
                msg += f"• {o}\n"
            msg += "\n"
        if big_ideas:
            msg += "<b>Большие идеи:</b>\n"
            for bi in big_ideas:
                msg += f"• {bi.get('title', '?')} ({bi.get('impact', '?')})\n"
            msg += "\n"
        if report:
            msg += f"_{report}_"

        await self._notify(msg, parse_mode="HTML")

        self._last_weekly = datetime.now()
        logger.info("=== Weekly review completed ===")

    async def continue_after_approval(self, numbers_str: str) -> str:
        """Called when user replies with numbers like '1 2 4'. Filters ideas and continues pipeline."""
        import json as _json
        pending_path = Path(self.project_root) / ".pending_ideas.json"

        if not pending_path.exists():
            return "Нет ожидающих идей для одобрения. Возможно, цикл ещё не запускался."

        # Parse numbers from user message
        try:
            selected = set()
            for part in numbers_str.split():
                part = part.strip(",. ")
                if part.isdigit():
                    selected.add(int(part))
        except (ValueError, TypeError):
            return "Не смог разобрать номера. Отправь цифры через пробел: 1 2 4"

        if not selected:
            return "Не нашёл номеров в сообщении. Отправь цифры: 1 2 4"

        # Load all pending ideas
        all_ideas = _json.load(pending_path.open("r", encoding="utf-8"))
        filtered = [idea for idx, idea in enumerate(all_ideas, 1) if idx in selected]

        # Remove pending file
        pending_path.unlink(missing_ok=True)

        if not filtered:
            return f"Номера {sorted(selected)} не подходят. Всего было {len(all_ideas)} идей. Ничего не делаю."

        await self._notify(
            f"👍 Принято! {len(filtered)} из {len(all_ideas)} идей идут в работу:\n"
            f"{', '.join(str(s) for s in sorted(selected))}\n\n"
            f"🔄 Запускаю Разработчика..."
        )

        # Continue pipeline with selected ideas
        await self._continue_with_ideas(filtered)
        return "ok"

    async def _continue_with_ideas(self, ideas: list[dict]):
        """Steps 2-4: review, refine, implement — run with the given ideas."""
        # --- Step 2: Developer reviews ---
        await self._notify("🔍 Агент-Разработчик проверяет логи и анализирует идеи...")
        logger.info("Step 2: Developer reviewing ideas")

        log_analysis = await self.developer.analyze_logs()
        project_state = await self.developer.analyze_project_state()
        review = await self.developer.review(ideas, log_analysis, project_state)

        reviews = review.get("reviews", [])
        log_insights = review.get("log_insights", "")
        arch_notes = review.get("architecture_notes", "")

        # Save reviews to DB
        for i, rev in enumerate(reviews):
            parent_id = None
            if i < len(ideas):
                recent = await self.repo.list_ideas(round="generation", status="pending", limit=10)
                if recent and i < len(recent):
                    parent_id = recent[-(i + 1)]["id"]
            await self.repo.create_idea(
                content=f"Verdict: {rev.get('verdict', '?')}. {rev.get('feedback', '')}",
                round="review",
                agent="developer",
                parent_id=parent_id,
                status="completed"
            )

        approved = [r for r in reviews if r.get("verdict") == "approved"]
        rejected = [r for r in reviews if r.get("verdict") == "rejected"]
        needs_work = [r for r in reviews if r.get("verdict") == "needs_revision"]

        review_msg = (
            f"📊 Разработчик проверил идеи:\n"
            f"✅ Одобрено: {len(approved)}\n"
            f"🔧 Нужна доработка: {len(needs_work)}\n"
            f"❌ Отклонено: {len(rejected)}\n"
        )
        if log_insights:
            review_msg += f"\n📋 Из логов: {log_insights[:300]}"
        if arch_notes:
            review_msg += f"\n🏗 По архитектуре: {arch_notes[:300]}"
        await self._notify(review_msg)

        # --- Step 3: Refinement ---
        if needs_work:
            await self._notify("🔄 Генератор дорабатывает идеи с учётом замечаний...")
            logger.info("Step 3: Generator refining ideas")

            feedback_text = "\n".join(
                f"Идея: {r.get('idea_title', '')}\n"
                f"Вердикт: {r.get('verdict', '')}\n"
                f"Фидбек: {r.get('feedback', '')}"
                for r in reviews
            )

            project_info = await self.generator.analyze_project()
            trends = await self.generator.search_trends()
            refined = await self.generator.brainstorm(
                project_info, trends, previous_feedback=feedback_text
            )
            refined_ideas = refined.get("ideas", [])
            refined_summary = refined.get("summary", "")

            for idea in refined_ideas:
                await self.repo.create_idea(
                    content=f"{idea.get('title', '')}: {idea.get('what', '')}",
                    round="refinement",
                    agent="generator",
                    status="pending"
                )

            await self._notify(
                f"✨ Генератор доработал идеи. Теперь {len(refined_ideas)} предложений.\n\n"
                f"_{refined_summary}_"
            )

            approved_ideas = []
            for r in approved:
                review_title = r.get("idea_title", "").strip().lower()
                for idea in ideas:
                    if idea.get("title", "").strip().lower() == review_title:
                        approved_ideas.append(idea)
                        break
            all_approved = approved_ideas + refined_ideas
        else:
            approved_ideas = []
            for r in approved:
                review_title = r.get("idea_title", "").strip().lower()
                for idea in ideas:
                    if idea.get("title", "").strip().lower() == review_title:
                        approved_ideas.append(idea)
                        break
            all_approved = approved_ideas

        # --- Step 4: Implementation ---
        effort_order = {"low": 0, "medium": 1, "high": 99}
        impact_order = {"high": 0, "medium": 1, "low": 2}

        for_impl = [i for i in all_approved if isinstance(i, dict) and i.get("effort") != "high"]
        for_weekly = [i for i in all_approved if isinstance(i, dict) and i.get("effort") == "high"]

        if for_weekly:
            heavy_titles = ", ".join(i.get("title", "?") for i in for_weekly)
            await self._notify(f"📦 Тяжёлые идеи отложены на еженедельный обзор: {heavy_titles}")

        implementable = sorted(
            for_impl,
            key=lambda i: (effort_order.get(i.get("effort", "medium"), 1),
                          impact_order.get(i.get("impact", "low"), 2))
        )

        if implementable:
            await self._notify(f"🔨 Разработчик внедряет {len(implementable[:2])} идей (лёгкие и средние)...")
            logger.info(f"Step 4: Developer implementing {len(implementable[:2])} ideas")

            for idea in implementable[:2]:
                await self._notify(f"🔧 Внедряю: {idea.get('title', '?')} (сложность: {idea.get('effort', '?')})...")
                impl_result = await self.developer.implement(idea)

                await self.repo.create_idea(
                    content=f"Implementation result: {impl_result[:500]}",
                    round="implementation",
                    agent="developer",
                    status="completed"
                )

                await self._update_readme_changelog(idea)

                try:
                    import subprocess
                    root = Path(self.project_root)
                    subprocess.run(["git", "add", "-A"], cwd=str(root),
                                  capture_output=True, timeout=15)
                    result = subprocess.run(
                        ["git", "diff", "--cached", "--stat"],
                        cwd=str(root), capture_output=True, text=True, timeout=15
                    )
                    if result.stdout.strip():
                        msg = f"Agent-implemented: {idea.get('title', 'improvement')}"
                        subprocess.run(["git", "commit", "-m", msg],
                                      cwd=str(root), capture_output=True, timeout=15)
                        subprocess.run(["git", "push"], cwd=str(root),
                                      capture_output=True, timeout=15)
                        await self._notify(f"✅ Внедрено и залито на гитхаб: {idea.get('title', '?')}")
                    else:
                        await self._notify(f"📝 Для «{idea.get('title', '?')}» сгенерирован план внедрения, лежит в базе идей")
                except Exception as e:
                    logger.warning(f"Git operation failed: {e}")
        else:
            await self._notify("⚠️ Нет идей для немедленного внедрения (все тяжёлые — уйдут в еженедельный обзор)")

        await self._notify(
            f"🏁 Цикл саморазвития завершён.\n\n"
            f"Сгенерировано идей: {len(ideas)}\n"
            f"Одобрено: {len(approved)}\n"
            f"Отклонено: {len(rejected)}\n"
            f"Попыток внедрения: {len(implementable[:2])}\n\n"
            f"Следующий цикл — через 2 дня."
        )
        logger.info("=== Agent cycle completed ===")

    async def _notify(self, text: str, parse_mode: str | None = None):
        """Send message to user via out_queue and Telegram, splitting if needed."""
        logger.info(f"Agent notification: {text[:100]}...")
        if self.out_queue:
            await self.out_queue.put({"text": text, "source": "agent"})

        # Also send directly via Telegram
        try:
            import httpx
            token = None
            env_path = Path(self.project_root) / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break

            if token and self.user_id:
                # Split long messages (Telegram limit: 4096 chars)
                max_len = 4000
                chunks = []
                if len(text) <= max_len:
                    chunks = [text]
                else:
                    # Split by paragraphs first, then by lines
                    paragraphs = text.split("\n\n")
                    current = ""
                    for para in paragraphs:
                        if len(current) + len(para) + 2 <= max_len:
                            current = (current + "\n\n" + para) if current else para
                        else:
                            if current:
                                chunks.append(current)
                            if len(para) <= max_len:
                                current = para
                            else:
                                # Split long paragraph by lines
                                lines = para.split("\n")
                                current = ""
                                for line in lines:
                                    if len(current) + len(line) + 1 <= max_len:
                                        current = (current + "\n" + line) if current else line
                                    else:
                                        if current:
                                            chunks.append(current)
                                        current = line
                    if current:
                        chunks.append(current)

                async with httpx.AsyncClient(timeout=15) as client:
                    for chunk in chunks:
                        body = {"chat_id": self.user_id, "text": chunk}
                        if parse_mode:
                            body["parse_mode"] = parse_mode
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json=body
                        )
        except Exception as e:
            logger.error(f"Failed to send agent TG message: {e}")

    async def _update_readme_changelog(self, idea: dict):
        """Update README.md changelog with the implemented idea, then commit and push."""
        try:
            readme_path = Path(self.project_root) / "README.md"
            if not readme_path.exists():
                return

            title = idea.get("title", "unknown")
            what = idea.get("what", "")[:150]

            lines = readme_path.read_text(encoding="utf-8").splitlines()
            today = datetime.now().strftime("%Y-%m-%d")

            new_lines = []
            inserted = False
            i = 0
            while i < len(lines):
                line = lines[i]
                new_lines.append(line)

                if "<!-- CHANGELOG_START -->" in line and not inserted:
                    inserted = True
                    i += 1
                    # Skip empty lines after the marker
                    while i < len(lines) and lines[i].strip() == "":
                        new_lines.append(lines[i])
                        i += 1

                    # Find existing date section for today, or insert new one
                    found_date = False
                    date_header = f"### {today}"
                    # Check if today already has a section
                    remaining = lines[i:]
                    for j, rl in enumerate(remaining):
                        if rl.startswith("### ") and today in rl:
                            found_date = True
                            break
                        if "<!-- CHANGELOG_END -->" in rl:
                            break

                    if not found_date:
                        new_lines.append("")
                        new_lines.append(date_header)

                    new_lines.append(f"* {title} — {what}")
                    continue

                i += 1

            if inserted:
                readme_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

                # Commit and push
                import subprocess
                root = str(Path(self.project_root))
                subprocess.run(["git", "add", "README.md"], cwd=root,
                              capture_output=True, timeout=15)
                msg = f"📝 README: {title}"
                subprocess.run(["git", "commit", "-m", msg],
                              cwd=root, capture_output=True, timeout=15)
                subprocess.run(["git", "push"], cwd=root,
                              capture_output=True, timeout=15)
                logger.info(f"README changelog updated: {title}")
        except Exception as e:
            logger.warning(f"Failed to update README changelog: {e}")
