from ..services.calendar_event_service import CalendarEventService, CalendarEventExternalService
from fastapi import APIRouter, HTTPException
from datetime import datetime
from ..utils.decorators import handle_errors   # ← add

router = APIRouter(prefix="/calendar-events", tags=["Calendar Events"])


@router.post("/")
@handle_errors                                 # ← add
async def create_calendar_event(payload: dict):
    service = CalendarEventService()
    return await service.create_event(payload)


@router.get("/")
@handle_errors                                 # ← add
async def get_calendar_events(
    start: str,
    end: str,
    user_id: int = None,
    email: str = None
):
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt   = datetime.fromisoformat(end.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO format.")

    if user_id:
        events = await CalendarEventExternalService.get_aggregated_events(user_id, start_dt, end_dt)
        return {"status": "success", "type": "internal", "user_id": user_id, "data": events}

    elif email:
        events = await CalendarEventExternalService.get_events_by_email(email, start_dt, end_dt)
        return {"status": "success", "type": "external", "email": email, "data": events}

    raise HTTPException(status_code=400, detail="Provide either user_id or email")