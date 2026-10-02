import json
import random
import time
import uuid
from typing import ClassVar

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleCalendarClient:
    SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, credentials_json: str):
        credentials_info = json.loads(credentials_json)

        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=self.SCOPES,
        )

        self._service = build(
            "calendar",
            "v3",
            credentials=credentials,
        )

    def _execute(self, request):
        # Serial calls plus bounded exponential backoff avoid write bursts.
        for attempt in range(7):
            time.sleep(0.25)
            try:
                return request.execute()
            except HttpError as exc:
                status = exc.resp.status
                retryable = status in {429, 500, 502, 503, 504}
                if status == 403:
                    try:
                        errors = json.loads(exc.content).get("error", {}).get("errors", [])
                        retryable = any(error.get("reason") in {
                            "rateLimitExceeded", "userRateLimitExceeded"
                        } for error in errors)
                    except (ValueError, TypeError):
                        retryable = False
                if not retryable or attempt == 6:
                    raise
                delay = min(60, 2 ** attempt + random.random())
                try:
                    delay = max(delay, min(120, float(exc.resp.get("retry-after", 0))))
                except (TypeError, ValueError):
                    pass
                time.sleep(delay)

    def get_calendar(self, calendar_id: str):
        return self._execute(self._service.calendars().get(calendarId=calendar_id))

    def create_event(self, calendar_id: str, event: dict):
        # Reuse one legal Google ID across retries, including an ambiguous 5xx.
        body = {**event, "id": uuid.uuid4().hex}
        try:
            return self._execute(self._service.events().insert(calendarId=calendar_id, body=body))
        except HttpError as exc:
            if exc.resp.status != 409:
                raise
            existing = self._execute(self._service.events().get(calendarId=calendar_id, eventId=body["id"]))
            if existing.get("extendedProperties") != body.get("extendedProperties"):
                raise RuntimeError("Event ID conflict; refusing to adopt event") from exc
            return existing

    def list_events(self, calendar_id: str):
        events = []
        page_token = None
        while True:
            response = self._execute(
                self._service.events()
                .list(
                    calendarId=calendar_id,
                    singleEvents=True,
                    maxResults=2500,
                    pageToken=page_token,
                )
            )
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return events

    def update_event(self, calendar_id: str, event_id: str, event: dict):
        return self._execute(
            self._service.events()
            .update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
            )
        )

    def delete_event(self, calendar_id: str, event_id: str):
        return self._execute(
            self._service.events()
            .delete(
                calendarId=calendar_id,
                eventId=event_id,
            )
        )
