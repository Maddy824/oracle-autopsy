"""Where paper alerts go: the terminal, macOS notifications, or the owner's Telegram chat.

Telegram credentials live in ~/.config/oracle-autopsy/telegram.json, mode 600:
{"bot_token": "...", "chat_id": "..."}. Create the bot with @BotFather and
send it one message so it may reply. Never log the token or the response.
"""

import json
from pathlib import Path
import stat
import subprocess
import sys

import httpx


TELEGRAM_CONFIG = Path("~/.config/oracle-autopsy/telegram.json")


def format_alert(alert):
    at = alert.time.strftime("%H:%M")
    if alert.side == "BUY":
        return (f"PAPER BUY {alert.symbol} ₹{alert.price:,.2f} at {at}. "
                f"Broke the 15-min high ₹{alert.range_high:,.2f}. "
                f"Stop ₹{alert.stop:,.2f}, target ₹{alert.target:,.2f}. Paper only, not advice.")
    why = {"stop": "closed below the range low", "target": "reached the 2R target",
           "time": "15:15 square-off", "data_end": "data ended"}[alert.reason]
    return f"PAPER SELL {alert.symbol} ₹{alert.price:,.2f} at {at}: {why}. Paper only, not advice."


class ConsoleNotifier:
    def send(self, text):
        print(text, flush=True)


class MacNotifier:
    def send(self, text):
        # json.dumps yields a double-quoted string with backslash escapes, which AppleScript accepts.
        script = f'display notification {json.dumps(text)} with title "Oracle Autopsy (paper)" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


class TelegramError(RuntimeError):
    """Sanitized Telegram failure: never contains the token or response body."""


class TelegramNotifier:
    def __init__(self, config_path=TELEGRAM_CONFIG, *, transport=None):
        path = Path(config_path).expanduser()
        try:
            if stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise ValueError()
            config = json.loads(path.read_text(encoding="utf-8"))
            self._token, self._chat = str(config["bot_token"]), str(config["chat_id"])
        except (OSError, ValueError, KeyError, TypeError):
            raise TelegramError(f"Telegram config missing, unreadable or not mode 600: {path}") from None
        self._transport = transport

    def send(self, text):
        try:
            with httpx.Client(transport=self._transport, timeout=15., trust_env=False) as client:
                response = client.post(f"https://api.telegram.org/bot{self._token}/sendMessage",
                                       json={"chat_id": self._chat, "text": text})
        except httpx.HTTPError:
            raise TelegramError("Telegram send failed (network)") from None
        if response.status_code != 200:
            raise TelegramError(f"Telegram send failed (HTTP {response.status_code})")


class TelegramInbox:
    """Read new text messages from the owner's configured chat only.

    Starts after the newest pending update, so old messages are never replayed.
    Returns texts; never logs them (a pasted Kite redirect holds a request token).
    """

    def __init__(self, config_path=TELEGRAM_CONFIG, *, transport=None):
        sender = TelegramNotifier(config_path, transport=transport)
        self._token, self._chat, self._transport = sender._token, sender._chat, transport
        self._offset = None
        updates = self._updates()
        self._offset = max((u["update_id"] for u in updates), default=-1) + 1

    def _updates(self):
        params = {"timeout": 0} if self._offset is None else {"timeout": 0, "offset": self._offset}
        try:
            with httpx.Client(transport=self._transport, timeout=15., trust_env=False) as client:
                response = client.get(f"https://api.telegram.org/bot{self._token}/getUpdates", params=params)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise TelegramError("Telegram read failed (network)") from None
        if response.status_code != 200 or not data.get("ok"):
            raise TelegramError(f"Telegram read failed (HTTP {response.status_code})")
        return [u for u in data.get("result", []) if isinstance(u.get("update_id"), int)]

    def poll(self):
        try:
            updates = self._updates()
        except TelegramError:
            return []
        if updates:
            self._offset = max(u["update_id"] for u in updates) + 1
        texts = []
        for update in updates:
            message = update.get("message") or {}
            if str((message.get("chat") or {}).get("id")) == self._chat and isinstance(message.get("text"), str):
                texts.append(message["text"])
        return texts


class FanOut:
    def __init__(self, notifiers):
        self.notifiers = notifiers

    def send(self, text):
        for notifier in self.notifiers:
            notifier.send(text)


def notifier_for(names):
    factories = {"console": ConsoleNotifier, "mac": MacNotifier, "telegram": TelegramNotifier}
    unknown = set(names) - set(factories)
    if unknown:
        raise ValueError(f"unknown notifier: {', '.join(sorted(unknown))}")
    return FanOut([factories[name]() for name in names])


def notify_kite_login(telegram=True):
    """Best-effort reminder; Telegram is used only when already configured."""
    message = "Oracle Autopsy: log in to Kite for today (valid until 06:00 tomorrow). Use the browser tab on this Mac."
    try:
        MacNotifier().send(message)
    except OSError:
        print('Mac notification unavailable; use the login browser tab on this Mac.', file=sys.stderr)
    if telegram and TELEGRAM_CONFIG.expanduser().exists():
        try:
            TelegramNotifier().send(message)
        except TelegramError:
            print('Telegram notification unavailable; use the login browser tab on this Mac.', file=sys.stderr)
