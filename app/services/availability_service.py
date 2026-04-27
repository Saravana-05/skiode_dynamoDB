from datetime import datetime, timedelta

from ..db.repositories import calendar_event_repo
from .calendar_account_service import get_user_accounts
from ..providers.google_provider import GoogleProvider
from ..providers.outlook_provider import OutlookProvider


class AvailabilityService:

    @staticmethod
    async def is_available(user_id, start, end):
        start_iso = start.isoformat() if isinstance(start, datetime) else start
        end_iso = end.isoformat() if isinstance(end, datetime) else end

        # Check internal DynamoDB calendar
        has_conflict = await calendar_event_repo.check_conflict(str(user_id), start_iso, end_iso)
        if has_conflict:
            return False, "Busy in internal calendar"

        # Check external providers
        accounts = await get_user_accounts(user_id)
        for acc in accounts:
            provider = acc["provider"]
            try:
                if provider == "GOOGLE":
                    busy = await GoogleProvider.get_free_busy(acc, start, end)
                elif provider == "OUTLOOK":
                    busy = await OutlookProvider.get_free_busy(acc, start, end)
                else:
                    continue

                if busy:
                    return False, f"Busy in {provider} calendar"

            except Exception as e:
                print(f"{provider} availability check failed:", str(e))

        return True, None

    @staticmethod
    async def check_internal(user_id, start, end):
        start_iso = start.isoformat() if isinstance(start, datetime) else start
        end_iso = end.isoformat() if isinstance(end, datetime) else end
        return await calendar_event_repo.check_conflict(str(user_id), start_iso, end_iso)

    @staticmethod
    async def are_users_available(user_ids: list, start, end):
        busy_users = []
        for user_id in user_ids:
            is_free, reason = await AvailabilityService.is_available(user_id, start, end)
            if not is_free:
                busy_users.append({"user_id": user_id, "reason": reason})

        return {"all_available": len(busy_users) == 0, "busy_users": busy_users}

    @staticmethod
    async def get_free_slots(user_ids, start, end, duration_minutes=30):
        slots = []
        current = start
        delta = timedelta(minutes=duration_minutes)

        while current + delta <= end:
            slot_start = current
            slot_end = current + delta
            availability = await AvailabilityService.are_users_available(user_ids, slot_start, slot_end)
            if availability["all_available"]:
                slots.append({"start": slot_start.isoformat(), "end": slot_end.isoformat()})
            current += delta

        return slots
