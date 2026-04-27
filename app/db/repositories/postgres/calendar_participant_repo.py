import json
from ....core.database import execute, fetch, fetchrow


async def create(event_id, role, name, email, user_id=None, status="pending", extra=None):
    row = await fetchrow(
        """
        INSERT INTO calendar_participants (event_id, user_id, role, name, email, status, extra)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING id
        """,
        int(event_id),
        int(user_id) if user_id else None,
        role, name, email, status,
        json.dumps(extra) if extra else None,
    )
    return str(row["id"])


async def get_by_event(event_id):
    rows = await fetch(
        "SELECT * FROM calendar_participants WHERE event_id = $1 ORDER BY id ASC",
        int(event_id),
    )
    return [dict(r) for r in rows]


async def get_by_email(email):
    rows = await fetch(
        "SELECT * FROM calendar_participants WHERE email = $1 ORDER BY created_at DESC",
        email,
    )
    return [dict(r) for r in rows]


async def get_events_by_email(email, start_dt, end_dt):
    rows = await fetch(
        """
        SELECT e.*
        FROM calendar_events e
        JOIN calendar_participants p ON e.id = p.event_id
        WHERE p.email = $1
          AND e.start_datetime >= $2
          AND e.end_datetime   <= $3
        ORDER BY e.start_datetime DESC
        """,
        email, start_dt, end_dt,
    )
    return [dict(r) for r in rows]


async def update_status(participant_id, status):
    await execute(
        "UPDATE calendar_participants SET status=$2, updated_at=CURRENT_TIMESTAMP WHERE id=$1",
        int(participant_id), status,
    )
