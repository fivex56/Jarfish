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


class CalendarService:
    def __init__(self):
        self._service = None

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
                flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_PATH), SCOPES)
                creds = flow.run_local_server(port=0)
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
