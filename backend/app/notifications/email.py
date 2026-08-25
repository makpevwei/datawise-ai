"""Report email delivery -- Phase 4 continuation section 33.

Uses Python's standard-library smtplib/email over an explicit SMTP host,
not a third-party provider SDK: no email-sending capability existed in
this project before this phase (checked .env / .env.example / pyproject
before writing this), so there is no existing configured provider to
reuse, and smtplib needs no new dependency. If DataWise-AI/.env ever gets
SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM_EMAIL set, this becomes
live without any code change.
"""

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import Settings


class EmailNotConfiguredError(Exception):
    """Raised when SMTP settings are unset. Callers must report this
    honestly (e.g. HTTP 503) rather than claiming the email was sent."""


class EmailSendError(Exception):
    """Raised when SMTP is configured but the send itself fails (auth,
    connection, rejected recipient, ...). The message never contains the
    SMTP password."""


def is_email_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password and settings.smtp_from_email)


def send_report_email(
    *,
    settings: Settings,
    to_email: str,
    subject: str,
    body_text: str,
    attachment_bytes: bytes,
    attachment_filename: str,
) -> None:
    if not is_email_configured(settings):
        raise EmailNotConfiguredError(
            "Email delivery is not configured. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and "
            "SMTP_FROM_EMAIL in DataWise-AI/.env to enable it."
        )

    message = MIMEMultipart()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body_text, "plain"))

    attachment = MIMEApplication(attachment_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    message.attach(attachment)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_from_email, [to_email], message.as_string())
    except smtplib.SMTPException as exc:
        # Deliberately generic: an SMTP exception's str() can echo back
        # server responses that sometimes include the attempted
        # credentials -- never let that reach an API response.
        raise EmailSendError("The email could not be sent. Check the SMTP configuration and try again.") from exc
