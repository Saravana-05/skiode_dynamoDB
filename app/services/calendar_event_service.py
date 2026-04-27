from datetime import datetime, timezone

from .calendar_participant_service import CalendarParticipantService
from .provider_executor import ProviderExecutor
from ..domain.calendar_participant_domain import CalendarParticipant
from ..services.calendar_account_service import get_user_accounts
from ..providers.google_provider import GoogleProvider
from ..providers.outlook_provider import OutlookProvider

from ..db.repositories import calendar_event_repo as repo


class Obj:
    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)


def _to_naive_iso(dt: datetime) -> str:
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


class CalendarEventService:

    async def create_event(self, data):
        if isinstance(data, dict):
            data = Obj(data)

        data.timezone = getattr(data, "timezone", "UTC")
        data.status = getattr(data, "status", "SCHEDULED")
        data.event_type = getattr(data, "event_type", "TASK")

        if isinstance(data.start_datetime, str):
            data.start_datetime = datetime.fromisoformat(data.start_datetime)
        if isinstance(data.end_datetime, str):
            data.end_datetime = datetime.fromisoformat(data.end_datetime)

        start_iso = _to_naive_iso(data.start_datetime)
        end_iso = _to_naive_iso(data.end_datetime)

        row = await repo.create(
            created_by_id=str(data.created_by_id),
            title=data.title,
            description=getattr(data, "description", None),
            start_datetime=start_iso,
            end_datetime=end_iso,
            timezone_str=data.timezone,
            status=data.status,
            event_type=data.event_type,
        )

        event_id = row["id"]
        participants = getattr(data, "participants", [])

        for p in participants:
            participant = CalendarParticipant(
                event_id=event_id,
                user_id=p.get("user_id"),
                role=p["role"],
                name=p.get("name"),
                email=p.get("email"),
                extra=p.get("extra", {}),
            )
            await CalendarParticipantService.create_participant(participant)

        attendees = [
            {"email": p.get("email"), "displayName": p.get("name")}
            for p in participants if p.get("email")
        ]

        if data.event_type == "MEETING" and attendees:
            event = await repo.get_by_id(event_id)
            await self.sync_event_with_providers(event, attendees)

        return {
            "status": "success",
            "event": {
                "id": event_id,
                "title": data.title,
                "event_type": data.event_type,
                "participants_count": len(participants),
                "is_synced": data.event_type == "MEETING" and bool(attendees),
            },
        }

    async def add_participants(self, event_id: str, participants: list):
        for p in participants:
            participant = CalendarParticipant(
                event_id=event_id,
                user_id=p.get("user_id"),
                role=p["role"],
                name=p.get("name"),
                email=p.get("email"),
                extra=p.get("extra", {}),
            )
            await CalendarParticipantService.create_participant(participant)

        event = await repo.get_by_id(event_id)

        if event["event_type"] != "MEETING":
            return {"status": "success", "message": "Participants added (no sync for TASK)", "event_id": event_id}

        all_participants = await CalendarParticipantService.get_participants_by_event(event_id)
        attendees = [{"email": p.email, "displayName": p.name} for p in all_participants if p.email]
        await self.sync_event_with_providers(event, attendees)

        return {"status": "success", "message": "Participants added & synced", "event_id": event_id}

    async def sync_event_with_providers(self, event: dict, attendees: list):
        accounts = await get_user_accounts(event["created_by_id"])

        for acc in accounts:
            provider = acc["provider"]
            try:
                if provider == "GOOGLE":
                    if event.get("google_event_id"):
                        await GoogleProvider.update_event(acc, event, attendees)
                    else:
                        google_id = await GoogleProvider.create_event(acc, event)
                        await repo.update_google_event_id(event["id"], google_id)

                elif provider == "OUTLOOK":
                    if event.get("outlook_event_id"):
                        await OutlookProvider.update_event(acc, event, attendees)
                    else:
                        outlook_id = await OutlookProvider.create_event(acc, event)
                        await repo.update_outlook_event_id(event["id"], outlook_id)

            except Exception as e:
                print(f"{provider} sync failed:", str(e))

    async def update_event(self, event_id: str, data):
        if isinstance(data, dict):
            data = Obj(data)

        data.timezone = getattr(data, "timezone", "UTC")
        data.status = getattr(data, "status", "SCHEDULED")

        if isinstance(data.start_datetime, str):
            data.start_datetime = datetime.fromisoformat(data.start_datetime)
        if isinstance(data.end_datetime, str):
            data.end_datetime = datetime.fromisoformat(data.end_datetime)

        start_iso = _to_naive_iso(data.start_datetime)
        end_iso = _to_naive_iso(data.end_datetime)

        await repo.update(
            event_id=event_id,
            title=data.title,
            description=getattr(data, "description", None),
            start_datetime=start_iso,
            end_datetime=end_iso,
            timezone_str=data.timezone,
            status=data.status,
        )

        event = await repo.get_by_id(event_id)

        if event["event_type"] != "MEETING":
            return {"status": "success", "message": "Event updated (TASK - no sync)", "event_id": event_id}

        participants = await CalendarParticipantService.get_participants_by_event(event_id)
        attendees = [{"email": p.email, "displayName": p.name} for p in participants if p.email]
        await self.sync_event_with_providers(event, attendees)

        return {"status": "success", "message": "Event updated & synced", "event_id": event_id}


class CalendarEventExternalService:

    @staticmethod
    async def get_events_by_email(email: str, start: datetime, end: datetime):
        from ..db.repositories import calendar_participant_repo
        start_iso = start.isoformat() if isinstance(start, datetime) else start
        end_iso = end.isoformat() if isinstance(end, datetime) else end
        return await calendar_participant_repo.get_events_by_email(email, start_iso, end_iso)

    @staticmethod
    async def get_aggregated_events(user_id, start: datetime, end: datetime):
        accounts = await get_user_accounts(user_id)
        all_events = []

        if not accounts:
            return []

        for acc in accounts:
            provider_name = acc["provider"]
            try:
                if provider_name == "GOOGLE":
                    provider = GoogleProvider()
                elif provider_name == "OUTLOOK":
                    provider = OutlookProvider()
                else:
                    continue

                res = await ProviderExecutor.execute(provider, acc, "get_events", start, end)
                all_events.extend(res.get("items", []))

            except Exception as e:
                all_events.append({"error": str(e), "provider": provider_name})

        return all_events
