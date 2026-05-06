"""
Notifier Service - Sends alerts for critical trading events
Supports console, email (SMTP), and webhook notifications
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class Notifier:
    """Send notifications via multiple channels"""

    def __init__(self, smtp_config: Optional[Dict] = None):
        import os
        self.smtp_config = smtp_config
        self.console_enabled = True
        self.email_enabled = smtp_config is not None
        self.webhook_url = None
        self.telegram_token   = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

    def send(self, subject: str, message: str, level: str = "INFO"):
        """Send notification via all enabled channels"""
        if self.console_enabled:
            self._send_console(subject, message, level)

        if self.email_enabled:
            self._send_email(subject, message)

        if self.webhook_url:
            self._send_webhook(subject, message)
        self._send_telegram(subject, message)

    def _send_console(self, subject: str, message: str, level: str):
        """Print to console with formatting"""
        prefix = {
            "INFO": "ℹ",
            "WARNING": "⚠️ ",
            "CRITICAL": "🚨",
            "ORDER": "📋",
        }.get(level, "ℹ")

        print(f"\n{prefix} {subject}")
        print(f"   {message}")
        print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    def _send_email(self, subject: str, message: str):
        """Send email via SMTP"""
        if not self.smtp_config:
            return
        try:
            msg = MIMEMultipart()
            msg['From'] = self.smtp_config['from']
            msg['To'] = self.smtp_config['to']
            msg['Subject'] = f"[SmartTrader] {subject}"

            msg.attach(MIMEText(message, 'plain'))

            with smtplib.SMTP(self.smtp_config['host'], self.smtp_config['port']) as server:
                if self.smtp_config.get('use_tls'):
                    server.starttls()
                if self.smtp_config.get('password'):
                    server.login(self.smtp_config['from'], self.smtp_config['password'])
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")

    def _send_webhook(self, subject: str, message: str):
        """Send webhook (Slack, Discord, etc.)"""
        try:
            import requests
            payload = {
                'text': f"*{subject}*\n{message}",
                'username': 'SmartTrader',
            }
            response = requests.post(self.webhook_url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(f"Webhook sent: {subject}")
            else:
                logger.warning(f"Webhook failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")


    def _send_telegram(self, subject: str, message: str):
        """Send Telegram bot notification — free, instant, mobile-ready."""
        if not self.telegram_token or not self.telegram_chat_id:
            return
        try:
            import requests as req
            text = f"*[SmartTrader] {subject}*\n{message}"
            url  = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            req.post(url, json={
                'chat_id': self.telegram_chat_id,
                'text': text, 'parse_mode': 'Markdown'
            }, timeout=5)
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    def notify_order(self, ticker: str, side: str, price: float, shares: int):
        """Notify order execution"""
        self.send(
            f"Order Executed: {ticker}",
            f"{side} {shares} shares @ ${price:.2f}",
            level="ORDER"
        )

    def notify_stop_loss(self, ticker: str, price: float, stop_price: float, pnl_pct: float):
        """Notify stop-loss hit"""
        self.send(
            f"STOP-LOSS HIT: {ticker}",
            f"Price: ${price:.2f} | Stop: ${stop_price:.2f} | P&L: {pnl_pct:+.2f}%",
            level="CRITICAL"
        )

    def notify_killswitch(self):
        """Notify kill-switch activation"""
        self.send(
            "KILL-SWITCH ACTIVATED",
            "All trading has been stopped. Manual re-enable required.",
            level="CRITICAL"
        )
