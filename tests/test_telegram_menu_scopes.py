import asyncio
import json

import httpx

from app.telegram_control import BOT_COMMANDS, TelegramControlClient


def test_owner_menu_replaces_default_private_and_owner_chat_scopes_for_english():
    calls = []

    async def handler(request: httpx.Request):
        calls.append((request.url.path, json.loads(request.content.decode())))
        return httpx.Response(200, json={"ok": True, "result": True})

    async def run():
        async with TelegramControlClient(
            bot_token="test-token",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.set_commands(chat_id="123456")

    asyncio.run(run())

    assert len(calls) == 6
    assert all(path.endswith("/setMyCommands") for path, _ in calls)
    assert all(payload["commands"] == BOT_COMMANDS for _, payload in calls)

    variants = {
        (
            json.dumps(payload.get("scope"), sort_keys=True),
            payload.get("language_code"),
        )
        for _, payload in calls
    }
    assert variants == {
        ("null", None),
        ("null", "en"),
        (json.dumps({"type": "all_private_chats"}, sort_keys=True), None),
        (json.dumps({"type": "all_private_chats"}, sort_keys=True), "en"),
        (json.dumps({"type": "chat", "chat_id": "123456"}, sort_keys=True), None),
        (json.dumps({"type": "chat", "chat_id": "123456"}, sort_keys=True), "en"),
    }

    names = [item["command"] for item in BOT_COMMANDS]
    for forbidden in ("sell", "sellall", "stop", "papermode", "golive", "confirm", "tp", "sl", "strict", "loose", "setbuysol", "pending", "approve", "reject"):
        assert forbidden not in names
