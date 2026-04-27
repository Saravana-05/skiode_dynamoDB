from ..db.repositories import calendar_participant_repo as repo
from ..domain.calendar_participant_domain import CalendarParticipant


class CalendarParticipantService:

    @staticmethod
    async def create_participant(participant: CalendarParticipant) -> str:
        return await repo.create(
            event_id=str(participant.event_id),
            role=participant.role,
            name=participant.name,
            email=participant.email,
            user_id=str(participant.user_id) if participant.user_id else None,
            status=getattr(participant, "status", "pending"),
            extra=participant.extra or {},
        )

    @staticmethod
    async def get_participants_by_event(event_id) -> list[CalendarParticipant]:
        rows = await repo.get_by_event(str(event_id))
        return [
            CalendarParticipant(
                event_id=r["event_id"],
                user_id=r.get("user_id"),
                role=r["role"],
                name=r.get("name"),
                email=r.get("email"),
                extra=r.get("extra", {}),
                status=r.get("status", "pending"),
            )
            for r in rows
        ]

    @staticmethod
    async def update_status(participant_id, status: str) -> None:
        await repo.update_status(str(participant_id), status)
