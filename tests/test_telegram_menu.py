import asyncio

from app.telegram_menu import OWNER_COMMAND_MENU, PROHIBITED_MENU_COMMANDS, sync_owner_command_menu


def test_owner_menu_contains_only_current_edge_lab_commands():
    names = [item["command"] for item in OWNER_COMMAND_MENU]
    assert names == [
        "help",
        "status",
        "balance",
        "pnl",
        "performance",
        "strategies",
        "evidence",
        "incidents",
        "pause",
        "resume",
        "freeze",
        "lifecycle",
        "incident",
    ]
    assert not (set(names) & PROHIBITED_MENU_COMMANDS)
    assert "golive" not in names
    assert "sell" not in names
    assert "sellall" not in names


def test_sync_replaces_telegram_persisted_menu_with_safe_commands():
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": True}

    asyncio.run(sync_owner_command_menu(fake_call))

    assert len(calls) == 1
    method, payload = calls[0]
    assert method == "setMyCommands"
    assert payload == {"commands": [dict(item) for item in OWNER_COMMAND_MENU]}
    assert all(not item["command"].startswith("/") for item in payload["commands"])
