from ..services.calendar_event_service import CalendarEventService, CalendarEventExternalService
from fastapi import APIRouter, Query
from datetime import datetime

router = APIRouter(prefix="/calendar-events", tags=["Calendar Events"])


@router.post("/")
async def create_calendar_event(payload: dict):
    """
    Create a new calendar event in local DB.
    Example payload:
    {
        "organization_id": 1,
        "created_by_id": 5,
        "title": "Interview",
        "description": "Frontend interview",
        "start_datetime": "2026-03-20T12:30:00",
        "end_datetime": "2026-03-20T13:30:00",
        "timezone": "Asia/Kolkata",
        "process_id": 1,
        "case_id": 100
    }
    """
    try:
        service = CalendarEventService()
        return await service.create_event(payload)
    except Exception as e:
        return {"status": "error", "message": str(e)}


# @router.get("/organization/{org_id}")
# async def get_org_events(org_id: int):
#     return await calendar_event_service.get_events(org_id)

# ----------------------------------------- calender event fetch -----


@router.get("/")
async def get_calendar_events(
    # email: str = Query(...),
    # start: str = Query(...),
    # end: str = Query(...)
    start: str,
    end: str,
    user_id: int = None,
    email: str = None
):
    try:
        # start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        # end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).replace(tzinfo=None)

        # SCENARIO 1: INTERNAL USER
        if user_id:
            events = await CalendarEventExternalService.get_aggregated_events(
                user_id,
                start_dt,
                end_dt
            )

            return {
                "status": "success",
                "type": "internal",
                "user_id": user_id,
                "data": events
            }

        # ✅ SCENARIO 2: EXTERNAL EMAIL
        elif email:
            events = await CalendarEventExternalService.get_events_by_email(
                email,
                start_dt,
                end_dt
            )

            return {
                "status": "success",
                "type": "external",
                "email": email,
                "data": events
            }

        return {
            "status": "error",
            "message": "Provide either user_id or email"
        }

    except ValueError:
        return {
            "status": "error",
            "message": "Invalid datetime format. Use ISO format."
        }

    except Exception as e:
        return {
            "status": "error",
            "message": "Failed to fetch calendar events",
            "details": str(e)
        }
