import smtplib
from email.message import EmailMessage

from sqlmodel import Session

from app.core.config import settings
from app.models.cloud_entities import BackgroundJob


def queue_account_email(
    session: Session,
    *,
    recipient: str,
    purpose: str,
    token_id: str,
) -> None:
    session.add(
        BackgroundJob(
            job_type="send_email",
            idempotency_key=f"email:{purpose}:{token_id}",
            payload_json={
                "recipient": recipient,
                "purpose": purpose,
                "token_id": token_id,
            },
        )
    )


def send_account_email(recipient: str, subject: str, text: str) -> bool:
    """Send without persisting the one-time token or message body on the server."""
    if not settings.smtp_host or not settings.smtp_from:
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        # Registration and recovery responses must not expose mail-provider
        # availability or turn into an account-enumeration side channel.
        return False
