import httpx
from urllib.parse import urlencode
from ..core.config import settings


class OutlookIntegration:

    AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def get_auth_url(self, state: str):

        params = {
            "client_id": settings.OUTLOOK_CLIENT_ID,
            "redirect_uri": settings.OUTLOOK_REDIRECT_URI,
            "response_type": "code",
            "scope": "offline_access Calendars.ReadWrite",
            "state": state
        }

        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_token(self, code: str):

        async with httpx.AsyncClient() as client:
            response = await client.post(self.TOKEN_URL, data={
                "client_id": settings.OUTLOOK_CLIENT_ID,
                "client_secret": settings.OUTLOOK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.OUTLOOK_REDIRECT_URI,
                "grant_type": "authorization_code"
            })

        if response.status_code != 200:
            raise Exception(response.text)

        return response.json()

    async def refresh_token(self, refresh_token: str):
        """ update token to avoid token expiry"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.OUTLOOK_CLIENT_ID,
                    "client_secret": settings.OUTLOOK_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "offline_access Calendars.ReadWrite"
                }
            )

        if response.status_code != 200:
            raise Exception(f"Outlook refresh failed: {response.text}")

        return response.json()
