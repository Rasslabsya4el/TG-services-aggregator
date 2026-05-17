from __future__ import annotations

import argparse
import asyncio
import getpass
import os

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactively create TG_SESSION_STRING for local Telegram fetch helpers."
    )
    parser.add_argument(
        "--api-id",
        type=int,
        default=None,
        help="Telegram API ID. Falls back to the TG_API_ID environment variable.",
    )
    parser.add_argument(
        "--api-hash",
        default=None,
        help="Telegram API hash. Falls back to the TG_API_HASH environment variable.",
    )
    return parser


def resolve_api_credentials(args: argparse.Namespace) -> tuple[int, str]:
    api_id_raw = args.api_id if args.api_id is not None else os.getenv("TG_API_ID", "").strip()
    api_hash = args.api_hash if args.api_hash is not None else os.getenv("TG_API_HASH", "").strip()

    if not api_id_raw:
        api_id_raw = input("Telegram API ID: ").strip()
    if not api_hash:
        api_hash = input("Telegram API hash: ").strip()

    try:
        api_id = int(str(api_id_raw).strip())
    except ValueError as exc:
        raise SystemExit("Telegram API ID must be an integer.") from exc

    if api_id <= 0:
        raise SystemExit("Telegram API ID must be a positive integer.")
    if not api_hash:
        raise SystemExit("Telegram API hash is required.")

    return api_id, api_hash


async def async_main() -> int:
    args = build_parser().parse_args()
    api_id, api_hash = resolve_api_credentials(args)

    phone = input("Phone number in international format (example: +381600000002): ").strip()
    if not phone:
        raise SystemExit("Phone number is required.")

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    try:
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            code = input("Telegram login code: ").strip()
            if not code:
                raise SystemExit("Telegram login code is required.")

            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass.getpass("Two-step verification password: ")
                if not password:
                    raise SystemExit("Two-step verification password is required.")
                await client.sign_in(password=password)

        session_string = client.session.save()
        if not session_string:
            raise SystemExit("Telethon did not return a session string.")

        print("\nTG_SESSION_STRING")
        print(session_string)
        print("\nExport this value in the runtime environment used by fetch helpers.")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
