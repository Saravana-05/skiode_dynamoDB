import httpx
from datetime import datetime


class OutlookProvider:

    BASE_URL = "https://graph.microsoft.com/v1.0"

    # create event in Outlook calendar(sync from local db)
    OUTLOOK_URL = "https://graph.microsoft.com/v1.0/me/events"

    # get existing event timings to avoid conflict when create event
    FREE_BUSY_URL = "https://graph.microsoft.com/v1.0/me/calendar/getSchedule"

    @staticmethod
    async def get_free_busy(account, start, end):

        payload = {
            "schedules": ["me"],
            "startTime": {
                "dateTime": start.isoformat(),
                "timeZone": "UTC"
            },
            "endTime": {
                "dateTime": end.isoformat(),
                "timeZone": "UTC"
            },
            "availabilityViewInterval": 30
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(
                OutlookProvider.FREE_BUSY_URL,
                headers={
                    "Authorization": f"Bearer {account['access_token']}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if res.status_code != 200:
            raise Exception(res.text)

        data = res.json().get("value", [])

        if data and data[0].get("scheduleItems"):
            return True

        return False

    async def get_calendars(self, account):

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.BASE_URL}/me/calendars",
                headers={
                    "Authorization": f"Bearer {account['access_token']}"
                }
            )

        if response.status_code != 200:
            raise Exception(f"Outlook calendar list error: {response.text}")

        return response.json()

    async def get_events(self, account, start: datetime, end: datetime):

        calendars = await self.get_calendars(account)

        all_events = []

        for cal in calendars.get("value", []):

            calendar_id = cal.get("id")
            calendar_name = cal.get("name", "Unknown")

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(
                        f"{self.BASE_URL}/me/calendars/{calendar_id}/calendarView",
                        headers={
                            "Authorization": f"Bearer {account['access_token']}"
                        },
                        params={
                            "startDateTime": start.isoformat(),
                            "endDateTime": end.isoformat()
                        }
                    )

                if response.status_code != 200:
                    continue

                data = response.json()

                for item in data.get("value", []):
                    all_events.append({
                        "title": item.get("subject", "No Title"),
                        "start": item.get("start", {}).get("dateTime"),
                        "end": item.get("end", {}).get("dateTime"),
                        "calendar": calendar_name,
                        "provider": "OUTLOOK"
                    })

            except Exception:
                continue

        return {"items": all_events}

    @staticmethod
    async def create_event(account, data):

        attendees = [
            {
                "emailAddress": {
                    "address": a["email"],
                    "name": a.get("displayName")
                },
                "type": "required"
            }
            for a in data.attendees
        ]

        payload = {
            "subject": data.title,
            "body": {
                "contentType": "HTML",
                "content": data.description or ""
            },
            "start": {
                "dateTime": data.start_datetime.isoformat(),
                "timeZone": data.timezone
            },
            "end": {
                "dateTime": data.end_datetime.isoformat(),
                "timeZone": data.timezone
            },
            "attendees": attendees
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(
                OutlookProvider.OUTLOOK_URL,
                headers={
                    "Authorization": f"Bearer {account['access_token']}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if res.status_code not in [200, 201]:
            raise Exception(f"Outlook error: {res.text}")

        return res.json().get("id")

    async def update_event(self, account, event, attendees):

        url = f"{self.BASE_URL}/me/events/{event['outlook_event_id']}"

        formatted_attendees = [
            {
                "emailAddress": {
                    "address": a["email"],
                    "name": a.get("displayName")
                },
                "type": "required"
            }
            for a in attendees
        ]

        payload = {
            "subject": event["title"],
            "body": {
                "contentType": "HTML",
                "content": event.get("description") or ""
            },
            "start": {
                "dateTime": event["start_datetime"].isoformat(),
                "timeZone": event["timezone"]
            },
            "end": {
                "dateTime": event["end_datetime"].isoformat(),
                "timeZone": event["timezone"]
            },
            "attendees": formatted_attendees
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
            raise Exception(f"Outlook update error: {res.text}")

        return True
