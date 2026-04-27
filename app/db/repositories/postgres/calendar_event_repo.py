from ....core.database import execute, fetch, fetchrow


async def create(created_by_id, title, description, start_datetime, end_datetime, timezone_str, status, event_type):
    row = await fetchrow(
        """
        INSERT INTO calendar_events
            (created_by_id, title, description, start_datetime, end_datetime, timezone, status, event_type)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        RETURNING id
        """,
        int(created_by_id), title, description, start_datetime, end_datetime, timezone_str, status, event_type,
    )
    return {"id": str(row["id"])}


async def get_by_id(event_id):
    row = await fetchrow("SELECT * FROM calendar_events WHERE id = $1", int(event_id))
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_by_id"] = str(d["created_by_id"])
    return d


async def get_events_by_creator(created_by_id):
    rows = await fetch(
        "SELECT * FROM calendar_events WHERE created_by_id = $1 ORDER BY start_datetime DESC",
        int(created_by_id),
    )
    result = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["created_by_id"] = str(d["created_by_id"])
        result.append(d)
    return result


async def update_google_event_id(event_id, google_event_id):
    await execute(
        "UPDATE calendar_events SET google_event_id = $2, updated_at = NOW() WHERE id = $1",
        int(event_id), google_event_id,
    )


async def update_outlook_event_id(event_id, outlook_event_id):
    await execute(
        "UPDATE calendar_events SET outlook_event_id = $2, updated_at = NOW() WHERE id = $1",
        int(event_id), outlook_event_id,
    )


async def update(event_id, title, description, start_datetime, end_datetime, timezone_str, status):
    await execute(
        """
        UPDATE calendar_events
        SET title=$1, description=$2, start_datetime=$3, end_datetime=$4,
            timezone=$5, status=$6, updated_at=NOW()
        WHERE id=$7
        """,
        title, description, start_datetime, end_datetime, timezone_str, status, int(event_id),
    )


async def check_conflict(created_by_id, start_dt, end_dt):
    rows = await fetch(
        """
        SELECT 1 FROM calendar_events
        WHERE created_by_id = $1 AND status = 'SCHEDULED'
          AND start_datetime < $3 AND end_datetime > $2
        LIMIT 1
        """,
        int(created_by_id), start_dt, end_dt,
    )
    return len(rows) > 0
