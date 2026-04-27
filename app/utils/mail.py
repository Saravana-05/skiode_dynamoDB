# import smtplib
# from email.mime.text import MIMEText
# from ..core.config import settings
#
#
# async def send_email(to: str, subject: str, body: str):
#
#     msg = MIMEText(body)
#     msg["Subject"] = subject
#     msg["From"] = settings.EMAIL_HOST_USER
#     msg["To"] = to
#
#     with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
#         server.starttls()
#         server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
#         server.send_message(msg)


import smtplib
from email.mime.text import MIMEText
from ..core.config import settings


async def send_email(to: str, subject: str, body: str):
    try:
        print("📧 Sending email to:", to)

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_HOST_USER
        msg["To"] = to

        print("SMTP HOST:", settings.EMAIL_HOST)
        print("SMTP PORT:", settings.EMAIL_PORT)

        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls()
            print("✅ TLS started")

            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            print("✅ Logged in")

            server.send_message(msg)
            print("✅ Email sent successfully")

    except Exception as e:
        print("❌ EMAIL ERROR:", str(e))
