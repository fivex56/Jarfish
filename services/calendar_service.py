import logging
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_PATH = BASE_DIR / "google_token.pickle"
OAUTH_PATH = BASE_DIR / "oauth_google.json"


class CalendarAuthError(Exception):
    """Raised when Google Calendar is not authorized yet."""
    pass


class CalendarService:
    def __init__(self):
        self._service = None
        self._auth_url = None  # Cached auth URL for manual completion

    def is_authorized(self) -> bool:
        """Check if we have a valid token without blocking."""
        if not OAUTH_PATH.exists():
            return False
        if not TOKEN_PATH.exists():
            return False
        try:
            with open(TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)
            return creds and creds.valid
        except Exception:
            return False

    def get_auth_url(self) -> str | None:
        """Get the OAuth URL for manual authorization. Returns None if already authorized."""
        if self.is_authorized():
            return None
        if not OAUTH_PATH.exists():
            return None
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_PATH), SCOPES)
            flow.redirect_uri = "http://localhost:8080"
            auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
            self._auth_url = auth_url
            return auth_url
        except Exception as e:
            logger.error(f"Failed to generate auth URL: {e}")
            return None

    def complete_auth(self, code: str) -> bool:
        """Complete OAuth flow with the authorization code from the URL callback."""
        if not self._auth_url:
            return False
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_PATH), SCOPES)
            flow.redirect_uri = "http://localhost:8080"
            flow.fetch_token(code=code)
            creds = flow.credentials
            with open(TOKEN_PATH, "wb") as f:
                pickle.dump(creds, f)
            self._service = None  # Reset cached service
            logger.info("Google Calendar authorized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to complete auth: {e}")
            return False

    async def _get_service(self):
        if self._service is None:
            import asyncio
            loop = asyncio.get_event_loop()
            self._service = await loop.run_in_executor(None, self._auth_sync)
        return self._service

    def _auth_sync(self):
        creds = None
        if TOKEN_PATH.exists():
            with open(TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                raise CalendarAuthError(
                    "Google Calendar not authorized. Use /calendar_auth to get the authorization URL, "
                    "open it in your browser, and send the 'code' parameter back with /calendar_code <code>."
                )
            with open(TOKEN_PATH, "wb") as f:
                pickle.dump(creds, f)

        return build("calendar", "v3", credentials=creds)

    async def list_events(self, days: int = 7, max_results: int = 20) -> list[dict]:
        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        def _list():
            now = datetime.utcnow().isoformat() + "Z"
            end = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
            events_result = service.events().list(
                calendarId="primary",
                timeMin=now,
                timeMax=end,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            return events_result.get("items", [])

        return await loop.run_in_executor(None, _list)

    async def create_event(self, summary: str, start_time: datetime,
                           end_time: datetime | None = None,
                           description: str = "",
                           reminders: list[dict] | None = None) -> dict:
        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        if end_time is None:
            end_time = start_time + timedelta(minutes=60)

        if reminders is None:
            reminders = [
                {"method": "popup", "minutes": 30},
                {"method": "popup", "minutes": 10},
            ]

        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Asia/Ho_Chi_Minh",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Asia/Ho_Chi_Minh",
            },
            "reminders": {
                "useDefault": False,
                "overrides": reminders,
            },
        }

        def _create():
            return service.events().insert(
                calendarId="primary",
                body=event,
                sendNotifications=True,
            ).execute()

        result = await loop.run_in_executor(None, _create)
        logger.info(f"Event created: {result.get('htmlLink')}")
        return result

    async def delete_event(self, event_id: str):
        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        def _delete():
            return service.events().delete(calendarId="primary", eventId=event_id).execute()

        return await loop.run_in_executor(None, _delete)

    async def update_event(self, event_id: str, **updates) -> dict:
        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        def _update():
            event = service.events().get(calendarId="primary", eventId=event_id).execute()
            for key, value in updates.items():
                if key == "start_time":
                    event["start"]["dateTime"] = value.isoformat()
                elif key == "end_time":
                    event["end"]["dateTime"] = value.isoformat()
                elif key == "reminders":
                    event["reminders"] = {"useDefault": False, "overrides": value}
                else:
                    event[key] = value
            return service.events().update(
                calendarId="primary", eventId=event_id, body=event, sendNotifications=True
            ).execute()

        return await loop.run_in_executor(None, _update)

    async def sync_events_to_tasks(self, repo) -> list[dict]:
        """Fetch upcoming calendar events and create/update tasks for them.
        Deadline = 1 hour before event start.
        Detects deleted events and cancels their tasks.
        Returns list of new/updated tasks."""
        from datetime import datetime as dt, timedelta

        events = await self.list_events(days=14, max_results=25)
        if not events:
            return []

        # Load synced event IDs from disk
        sync_file = BASE_DIR / "data" / "calendar_sync.json"
        synced_ids = {}
        if sync_file.exists():
            try:
                import json
                raw = json.loads(sync_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    synced_ids = {eid: "" for eid in raw}
                elif isinstance(raw, dict):
                    synced_ids = raw
            except Exception:
                synced_ids = {}

        result_tasks = []
        current_event_ids = set()

        for ev in events:
            event_id = ev.get("id", "")
            if not event_id:
                continue
            current_event_ids.add(event_id)

            summary = ev.get("summary", "Без названия")
            description = ev.get("description", "")
            start = ev.get("start", {})
            start_str = start.get("dateTime") or start.get("date") or ""
            end = ev.get("end", {})
            end_str = end.get("dateTime") or end.get("date") or ""
            location = ev.get("location", "")
            hangout_link = ev.get("hangoutLink", "")
            conference_link = ev.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri", "") if ev.get("conferenceData") else ""
            event_status = ev.get("status", "")

            # If event is cancelled in calendar — cancel the linked task
            if event_status == "cancelled":
                existing = await repo.find_task_by_calendar_event_id(event_id)
                if existing and existing.get("status") not in ("cancelled", "done"):
                    await repo.cancel_task(existing["id"])
                    logger.info(f"Calendar sync: cancelled task #{existing['id']} for cancelled event '{summary}'")
                continue

            # Build task description from event details
            desc_parts = []
            if description:
                desc_parts.append(description)
            if location:
                desc_parts.append(f"📍 {location}")
            if hangout_link:
                desc_parts.append(f"🔗 {hangout_link}")
            elif conference_link:
                desc_parts.append(f"🔗 {conference_link}")
            if end_str:
                try:
                    s = dt.fromisoformat(start_str)
                    e = dt.fromisoformat(end_str)
                    desc_parts.append(f"⏱ {s.strftime('%H:%M')} — {e.strftime('%H:%M')}")
                except Exception:
                    pass

            # Deadline = 1 hour before event start
            try:
                dt_start = dt.fromisoformat(start_str)
                deadline = (dt_start - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                deadline = (start_str[:10] + " 00:00") if len(start_str) >= 10 else ""

            is_new = event_id not in synced_ids
            task = await repo.upsert_task(
                calendar_event_id=event_id,
                title=f"📅 {summary}",
                description="\n".join(desc_parts),
                due_date=deadline,
                priority=1,
                tags="calendar"
            )

            if is_new:
                synced_ids[event_id] = ""
                result_tasks.append(task)
                logger.info(f"Calendar sync: created task '{summary}' deadline={deadline}")
            else:
                logger.info(f"Calendar sync: updated task '{summary}' deadline={deadline}")

        # Detect deleted events: cancel tasks for events no longer in calendar
        removed_ids = set(synced_ids.keys()) - current_event_ids
        for removed_id in removed_ids:
            existing = await repo.find_task_by_calendar_event_id(removed_id)
            if existing and existing.get("status") not in ("cancelled", "done"):
                await repo.cancel_task(existing["id"])
                logger.info(f"Calendar sync: cancelled task #{existing['id']} for removed event {removed_id}")
            del synced_ids[removed_id]

        # Save updated synced IDs
        import json
        sync_file.parent.mkdir(parents=True, exist_ok=True)
        sync_file.write_text(json.dumps(list(synced_ids.keys()), ensure_ascii=False), encoding="utf-8")

        return result_tasks

    # ── Task → Calendar export ───────────────────────────────────────────

    async def export_task_to_calendar(self, repo, task: dict) -> str | None:
        """Create a Google Calendar event for a task. Returns event_id or None."""
        if not task.get("due_date"):
            return None

        # Don't re-export tasks that were imported from calendar
        tags = task.get("tags", "")
        if "calendar" in tags and not task.get("calendar_event_id"):
            return None

        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        # Parse due_date as all-day or 09:00-09:30 event
        title = task.get("title", "").replace("📅 ", "")
        description = task.get("description", "")
        due = task.get("due_date", "")

        try:
            from datetime import datetime as dt
            # All-day event: set date (no time)
            if len(due) == 10:  # YYYY-MM-DD
                start_dt = dt.strptime(due, "%Y-%m-%d")
                event = {
                    "summary": title,
                    "description": description,
                    "start": {
                        "date": start_dt.strftime("%Y-%m-%d"),
                        "timeZone": "Asia/Ho_Chi_Minh",
                    },
                    "end": {
                        "date": (start_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                        "timeZone": "Asia/Ho_Chi_Minh",
                    },
                }
            else:
                # Has time portion
                start_dt = dt.fromisoformat(due)
                end_dt = start_dt + timedelta(minutes=30)
                event = {
                    "summary": title,
                    "description": description,
                    "start": {
                        "dateTime": start_dt.isoformat(),
                        "timeZone": "Asia/Ho_Chi_Minh",
                    },
                    "end": {
                        "dateTime": end_dt.isoformat(),
                        "timeZone": "Asia/Ho_Chi_Minh",
                    },
                }
        except Exception:
            return None

        def _create():
            return service.events().insert(
                calendarId="primary", body=event, sendNotifications=False
            ).execute()

        result = await loop.run_in_executor(None, _create)
        event_id = result.get("id")
        if event_id:
            await repo.update_task(task["id"], calendar_event_id=event_id)
            logger.info(f"Exported task '{title}' to calendar event {event_id}")
        return event_id

    async def update_task_event(self, repo, task: dict):
        """Update calendar event when task is modified."""
        event_id = task.get("calendar_event_id", "")
        if not event_id or not task.get("due_date"):
            # If task gained a due_date, create new event
            if task.get("due_date") and not event_id:
                await self.export_task_to_calendar(repo, task)
            return

        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        title = task.get("title", "").replace("📅 ", "")
        due = task.get("due_date", "")

        def _update():
            try:
                ev = service.events().get(calendarId="primary", eventId=event_id).execute()
                ev["summary"] = title
                ev["description"] = task.get("description", "")
                if len(due) == 10:
                    ev["start"] = {"date": due, "timeZone": "Asia/Ho_Chi_Minh"}
                    from datetime import datetime as dt
                    end_date = dt.strptime(due, "%Y-%m-%d") + timedelta(days=1)
                    ev["end"] = {"date": end_date.strftime("%Y-%m-%d"), "timeZone": "Asia/Ho_Chi_Minh"}
                return service.events().update(
                    calendarId="primary", eventId=event_id, body=ev, sendNotifications=False
                ).execute()
            except Exception as e:
                logger.error(f"Failed to update calendar event {event_id}: {e}")
                return None

        await loop.run_in_executor(None, _update)

    async def delete_task_event(self, task: dict):
        """Delete calendar event when task is deleted (not when done)."""
        event_id = task.get("calendar_event_id", "")
        if not event_id:
            return

        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        def _delete():
            try:
                service.events().delete(calendarId="primary", eventId=event_id).execute()
                logger.info(f"Deleted calendar event {event_id} for deleted task")
            except Exception as e:
                logger.error(f"Failed to delete calendar event {event_id}: {e}")

        await loop.run_in_executor(None, _delete)

    async def sync_task_status_to_calendar(self, repo, task: dict):
        """When a task is marked done/cancelled, reflect this in the calendar event.
        Done task → mark event with ✅ prefix. Cancelled → delete event."""
        event_id = task.get("calendar_event_id", "")
        if not event_id:
            return

        status = task.get("status", "")
        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        if status == "done":
            def _mark_done():
                try:
                    ev = service.events().get(calendarId="primary", eventId=event_id).execute()
                    ev["summary"] = "✅ " + ev.get("summary", "").lstrip("✅ ")
                    ev["colorId"] = "2"  # Green in Google Calendar
                    return service.events().update(
                        calendarId="primary", eventId=event_id, body=ev, sendNotifications=False
                    ).execute()
                except Exception as e:
                    logger.error(f"Failed to mark calendar event {event_id} done: {e}")
            await loop.run_in_executor(None, _mark_done)

        elif status == "cancelled":
            def _cancel():
                try:
                    service.events().delete(calendarId="primary", eventId=event_id).execute()
                    logger.info(f"Deleted calendar event {event_id} for cancelled task")
                except Exception as e:
                    logger.error(f"Failed to delete calendar event {event_id}: {e}")
            await loop.run_in_executor(None, _cancel)
            # Clear the link so we don't try to delete again
            await repo.update_task(task["id"], calendar_event_id="")

    async def export_reminder_to_calendar(self, repo, reminder: dict) -> str | None:
        """Create a Google Calendar event for a reminder. Returns event_id or None."""
        service = await self._get_service()
        import asyncio
        loop = asyncio.get_event_loop()

        try:
            from datetime import datetime as dt
            trigger = dt.fromisoformat(reminder["trigger_at"])
        except Exception:
            return None

        event = {
            "summary": f"⏰ {reminder['message']}",
            "start": {
                "dateTime": trigger.isoformat(),
                "timeZone": "Asia/Ho_Chi_Minh",
            },
            "end": {
                "dateTime": (trigger + timedelta(minutes=15)).isoformat(),
                "timeZone": "Asia/Ho_Chi_Minh",
            },
        }

        def _create():
            return service.events().insert(
                calendarId="primary", body=event, sendNotifications=False
            ).execute()

        result = await loop.run_in_executor(None, _create)
        event_id = result.get("id")
        if event_id:
            # Update reminder with calendar_event_id via raw SQL
            await repo.db.execute(
                "UPDATE reminders SET calendar_event_id = ? WHERE id = ?",
                (event_id, reminder["id"])
            )
            await repo.db.commit()
            logger.info(f"Exported reminder '{reminder['message'][:50]}' to calendar event {event_id}")
        return event_id

    async def sync_all_to_calendar(self, repo) -> dict:
        """Export all tasks and reminders that don't have calendar_event_id yet.
        Returns counts of created events."""
        tasks = await repo.list_tasks(limit=500)
        reminders = await repo.get_pending_reminders()

        task_count = 0
        for t in tasks:
            if t.get("due_date") and not t.get("calendar_event_id"):
                # Skip tasks that were imported FROM calendar
                tags = t.get("tags", "")
                if "calendar" in tags:
                    continue
                if await self.export_task_to_calendar(repo, t):
                    task_count += 1

        reminder_count = 0
        for r in reminders:
            if not r.get("calendar_event_id"):
                if await self.export_reminder_to_calendar(repo, r):
                    reminder_count += 1

        logger.info(f"Calendar export: {task_count} tasks, {reminder_count} reminders")
        return {"tasks": task_count, "reminders": reminder_count}
