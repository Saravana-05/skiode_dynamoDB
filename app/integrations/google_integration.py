import requests
import httpx
from urllib.parse import urlencode
from ..core.config import settings


class GoogleIntegration:

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def get_auth_url(self, state: str):

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/calendar",
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }

        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_token(self, code: str):

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code"
                }
            )

        if response.status_code != 200:
            raise Exception(response.text)

        return response.json()

    async def refresh_token(self, refresh_token: str):
        """ update token to avoid token expiry"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token"
                }
            )

        if response.status_code != 200:
            raise Exception(f"Google refresh failed: {response.text}")

        return response.json()
