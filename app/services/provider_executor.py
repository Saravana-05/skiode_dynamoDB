from ..integrations.google_integration import GoogleIntegration
from ..integrations.outlook_integration import OutlookIntegration
from ..services.calendar_account_service import update_tokens


class ProviderExecutor:

    @staticmethod
    async def execute(provider, account, method, *args):

        try:
            return await getattr(provider, method)(account, *args)

        except Exception as e:

            if "401" in str(e) or "Unauthorized" in str(e):

                # 🔁 Refresh token
                if account["provider"] == "GOOGLE":
                    token = await GoogleIntegration().refresh_token(
                        account["refresh_token"]
                    )

                elif account["provider"] == "OUTLOOK":
                    token = await OutlookIntegration().refresh_token(
                        account["refresh_token"]
                    )

                else:
                    raise

                # 💾 Update DB
                await update_tokens(
                    account["id"],
                    token.get("access_token"),
                    token.get("refresh_token", account["refresh_token"])
                )

                # 🔁 Retry API call
                account["access_token"] = token.get("access_token")

                return await getattr(provider, method)(account, *args)

            raise
