from config import Config
from gcalendar import GoogleCalendarClient
from logger import logger
from models import Event
from timetree import TimeTree


def _private_properties(google_event: dict) -> dict:
    return google_event.get("extendedProperties", {}).get("private", {})


def _is_managed_google_event(google_event: dict, calendar_code: str) -> bool:
    # Markerless older events are intentionally not adopted or deleted.
    props = _private_properties(google_event)
    return bool(props.get("timetree_id")) and (
        props.get("sync_source") == Event.SYNC_SOURCE
        and props.get("timetree_calendar_code") == calendar_code
    )


def _label_targets(labels: dict, mapping: dict[str, str]) -> dict[str, str]:
    targets = {}
    for name, target in mapping.items():
        ids = [str(key) for key, label in labels.items() if " ".join(str(label.get("name", "")).split()) == " ".join(name.split())]
        if len(ids) != 1:
            raise RuntimeError("Mapped TimeTree label is missing or ambiguous: " + name)
        targets[ids[0]] = target
    return targets


def _label_id(raw: dict) -> str | None:
    label_id = raw.get("label_id")
    if label_id is None:
        label_id = (raw.get("relationships", {}).get("label", {}).get("data") or {}).get("id")
    return str(label_id).split(",")[-1] if label_id is not None else None


def reconcile(google, desired: dict[str, list[Event]], calendar_code: str, legacy_id=None, cleanup=False):
    """Snapshot all calendars, finish every upsert, then clean strictly owned copies.

    Failure in the upsert phase deletes no existing source/target copies.
    A later run safely resumes from the partial set of successful target writes.
    """
    calendar_ids = list(desired)
    if legacy_id and legacy_id not in calendar_ids:
        calendar_ids.append(legacy_id)
    snapshots = {target: google.list_events(target) for target in calendar_ids}
    retained = set()
    created = updated = skipped = deleted = 0
    for target, events in desired.items():
        matches = {}
        for copy in snapshots[target]:
            if _is_managed_google_event(copy, calendar_code):
                source_id = str(_private_properties(copy)["timetree_id"])
                matches.setdefault(source_id, []).append(copy)
        for event in events:
            copies = matches.get(str(event.id), [])
            if copies:
                copy = copies[0]
                if not event.equals_google(copy, calendar_code):
                    google.update_event(target, copy["id"], event.to_google(calendar_code))
                    updated += 1
                else:
                    skipped += 1
                retained.add((target, copy["id"]))
            else:
                google.create_event(target, event.to_google(calendar_code))
                created += 1
    # Newly created events are not in snapshots and cannot be deleted here.
    for target, copies in snapshots.items():
        if not cleanup:
            continue
        for copy in copies:
            if _is_managed_google_event(copy, calendar_code) and (target, copy["id"]) not in retained:
                google.delete_event(target, copy["id"])
                deleted += 1
    logger.info("Sync complete: created=%d updated=%d deleted=%d skipped=%d", created, updated, deleted, skipped)


def sync():
    client = TimeTree()
    client.login(Config.TIMETREE_EMAIL, Config.TIMETREE_PASSWORD)
    calendar = client.get_calendar(Config.TIMETREE_CALENDAR_CODE)
    mapping = Config.calendar_map()
    # get_labels returns the original API label IDs; never infer labels from titles/colors.
    targets = _label_targets(calendar.get_labels(), mapping) if mapping else {}
    raw_events = client.get_events(calendar)
    desired = {target: [] for target in mapping.values()} if mapping else {Config.GOOGLE_CALENDAR_ID: []}
    seen = set()
    for raw in raw_events:
        target = targets.get(_label_id(raw)) if mapping else Config.GOOGLE_CALENDAR_ID
        if target is None:
            continue
        event = Event.from_timetree(raw)
        event.id = str(event.id)
        if event.id in seen:
            raise RuntimeError("Duplicate TimeTree event ID in source snapshot")
        seen.add(event.id)
        desired[target].append(event)
    google = GoogleCalendarClient(Config.GOOGLE_SERVICE_ACCOUNT_JSON)
    # Preflight all calendars before any writes or cleanup.
    for target in set(desired) | {Config.GOOGLE_CALENDAR_ID}:
        google.get_calendar(target)
    reconcile(google, desired, Config.TIMETREE_CALENDAR_CODE,
              Config.GOOGLE_CALENDAR_ID if mapping else None, cleanup=Config.GOOGLE_SYNC_CLEANUP)
