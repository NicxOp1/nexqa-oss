"""
NEXQA v1.0 — Email Notifier

Sends alerts for review requests, critical failures, and regression warnings.
"""

from typing import List, Optional
import smtplib
from email.mime.text import MIMEText
from nexqa.storage.config import Config
from nexqa.storage.logger import logger


class EmailNotifier:
    """Sends email alerts via SMTP."""

    def __init__(self) -> None:
        self.host = Config.SMTP_HOST
        self.port = Config.SMTP_PORT
        self.user = Config.SMTP_USER
        self.password = Config.SMTP_PASS
        self.to_email = Config.REVIEW_EMAIL_TO

    def send_review_request(
        self,
        agent_id: str,
        reason: str,
        score: float,
        issues: Optional[List[str]] = None,
    ) -> bool:
        """Send an email asking for human review."""
        issues = issues or []
        if not self.host or not self.to_email:
            logger.warning("Email not configured. Skipping alert.")
            return False

        subject = f"[NEXQA REVIEW] Agent {agent_id} needs attention (Score: {score:.2f})"
        top_issues = "\n".join(f"- {i}" for i in issues[:5])
        body = f"""
        NEXQA Review Request
        --------------------
        Agent: {agent_id}
        Reason: {reason}
        Current Score: {score:.2f}

        Top Issues:
        {top_issues}

        Please review the prompt and approve manually.
        """

        return self._send_email(subject, body)

    def _send_email(self, subject: str, body: str) -> bool:
        """Internal SMTP send."""
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.user
            msg["To"] = self.to_email

            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False


# Singleton
email_notifier = EmailNotifier()
