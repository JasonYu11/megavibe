from __future__ import annotations

from app.bot.command_menu import BOT_COMMANDS
from app.bot.runtime import TelegramHttpTransport
from app.secrets.provider import CompositeSecretProvider


def main() -> None:
    transport = TelegramHttpTransport("ENV:TELEGRAM_BOT_TOKEN", CompositeSecretProvider())
    transport.set_my_commands(BOT_COMMANDS)
    print(f"configured {len(BOT_COMMANDS)} Telegram bot commands")


if __name__ == "__main__":
    main()

