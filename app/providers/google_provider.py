import httpx
from datetime import datetime, timezone


class GoogleProvider:
    # get calendar events
    BASE_URL = "https://www.googleapis.com/calendar/v3"

    # create event in google calendar(sync from local db)
    GOOGLE_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    # get existing event timings to avoid conflict when create event
    FREE_BUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"

    @staticmethod
    async def get_free_busy(account, start, end):

        payload = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": "primary"}]
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(
                GoogleProvider.FREE_BUSY_URL,
                headers={
                    "Authorization": f"Bearer {account['access_token']}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if res.status_code != 200:
            raise Exception(res.text)

        busy = res.json()["calendars"]["primary"]["busy"]

        return len(busy) > 0

    async def get_calendar_list(self, account):

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.BASE_URL}/users/me/calendarList",
                headers={
                    "Authorization": f"Bearer {account['access_token']}"
                }
            )

        if response.status_code != 200:
            raise Exception(f"Google calendar list error: {response.text}")

        return response.json()

    async def get_events(self, account, start: datetime, end: datetime):

        calendars = await self.get_calendar_list(account)

        all_events = []

        for cal in calendars.get("items", []):

            calendar_id = cal.get("id")
            calendar_name = cal.get("summary", "Unknown")

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(
                        f"{self.BASE_URL}/calendars/{calendar_id}/events",
                        headers={
                            "Authorization": f"Bearer {account['access_token']}"
                        },
                        params={
                            "timeMin": start.isoformat(),
                            "timeMax": end.isoformat(),
                            "singleEvents": True,
                            "orderBy": "startTime"
                        }
                    )

                if response.status_code != 200:
                    continue

                data = response.json()

                for item in data.get("items", []):

                    start_dt = item.get("start", {}).get("dateTime")
                    end_dt = item.get("end", {}).get("dateTime")

                    # skip all-day events (optional)
                    if not start_dt or not end_dt:
                        continue

                    all_events.append({
                        "title": item.get("summary", "No Title"),
                        "start": start_dt,
                        "end": end_dt,
                        "calendar": calendar_name,
                        "provider": "GOOGLE"
                    })

            except Exception:
                continue  # skip broken calendar safely

        return {"items": all_events}

    @staticmethod
    async def create_event(account, data):

        payload = {
            "summary": data.title,
            "description": data.description or "",
            "start": {
                "dateTime": data.start_datetime.isoformat(),
                "timeZone": data.timezone
            },
            "end": {
                "dateTime": data.end_datetime.isoformat(),
                "timeZone": data.timezone
            },
            "attendees": data.attendees,
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(
                GoogleProvider.GOOGLE_URL,
                headers={
                    "Authorization": f"Bearer {account['access_token']}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if res.status_code not in [200, 201]:
            raise Exception(f"Google error: {res.text}")

        return res.json().get("id")

    async def update_event(self, account, event, attendees):

        url = f"{self.BASE_URL}/calendars/primary/events/{event['google_event_id']}"

        payload = {
            "summary": event["title"],
            "description": event.get("description") or "",
            "start": {
                "dateTime": event["start_datetime"].isoformat(),
                "timeZone": event["timezone"]
            },
            "end": {
                "dateTime": event["end_datetime"].isoformat(),
                "timeZone": event["timezone"]
            },
            "attendees": attendees
        }

        async with httpx.AsyncClient() as client:
            res = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {account['access_token']}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if res.status_code not in [200]:
            raise Exception(f"Google update error: {res.text}")

        return True
