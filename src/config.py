import json
import os


class Config:
    TIMETREE_EMAIL = os.getenv("TIMETREE_EMAIL")
    TIMETREE_PASSWORD = os.getenv("TIMETREE_PASSWORD")
    TIMETREE_CALENDAR_CODE = os.getenv("TIMETREE_CALENDAR_CODE")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

    GOOGLE_SYNC_CLEANUP = os.getenv("GOOGLE_SYNC_CLEANUP", "false").lower() == "true"
    GOOGLE_CALENDAR_MAP_JSON = os.getenv("GOOGLE_CALENDAR_MAP_JSON")

    @classmethod
    def calendar_map(cls) -> dict[str, str]:
        if not cls.GOOGLE_CALENDAR_MAP_JSON:
            return {}
        try:
            mapping = json.loads(cls.GOOGLE_CALENDAR_MAP_JSON)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("GOOGLE_CALENDAR_MAP_JSON must be a JSON object") from exc
        if not isinstance(mapping, dict) or not mapping or any(
            not isinstance(name, str) or not name.strip()
            or not isinstance(target, str) or not target.strip()
            for name, target in mapping.items()
        ):
            raise RuntimeError("Calendar map must contain nonempty label names and calendar IDs")
        approved = {"희돈 일정", "동동 일정", "부부 일정", "부부 가족 경조사"}
        normalized = {" ".join(name.split()): target for name, target in mapping.items()}
        if set(normalized) != approved or len(normalized) != len(mapping):
            raise RuntimeError("Calendar map must contain exactly the four approved labels")
        mapping = normalized
        if len(set(mapping.values())) != len(mapping):
            raise RuntimeError("Each mapped label must have a distinct Google calendar")
        if cls.GOOGLE_CALENDAR_ID in mapping.values():
            raise RuntimeError("Legacy calendar must not be a mapped target")
        return mapping

    @classmethod
    def validate(cls):
        required = {
            "TIMETREE_EMAIL": cls.TIMETREE_EMAIL,
            "TIMETREE_PASSWORD": cls.TIMETREE_PASSWORD,
            "TIMETREE_CALENDAR_CODE": cls.TIMETREE_CALENDAR_CODE,
            "GOOGLE_SERVICE_ACCOUNT_JSON": cls.GOOGLE_SERVICE_ACCOUNT_JSON,
            "GOOGLE_CALENDAR_ID": cls.GOOGLE_CALENDAR_ID,
        }
        cls.calendar_map()
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError("Missing environment variables: " + ", ".join(missing))
