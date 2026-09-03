from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

TelegramCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

# Telegram's setMyCommands API expects command names without a leading slash.
# Keep this list limited to commands actually supported by TelegramControlRouter.
OWNER_COMMAND_MENU: tuple[dict[str, str], ...] = (
    {"command": "help", "description": "Show Edge Lab owner controls"},
    {"command": "status", "description": "Overall paper/shadow research status"},
    {"command": "balance", "description": "Simulated paper/shadow NAV"},
    {"command": "pnl", "description": "Simulated P&L by research study"},
    {"command": "performance", "description": "Strategy and lifecycle performance"},
    {"command": "strategies", "description": "Current research strategies"},
    {"command": "evidence", "description": "Evidence progress and recommendations"},
    {"command": "incidents", "description": "Unresolved research incidents"},
    {"command": "pause", "description": "Pause a research study"},
    {"command": "resume", "description": "Resume a paused research study"},
    {"command": "freeze", "description": "Freeze a research study"},
    {"command": "lifecycle", "description": "Control Solana lifecycle research"},
    {"command": "incident", "description": "Acknowledge or resolve an incident"},
)

# Old Kennysbot/live-execution commands must never appear in the Edge Lab owner menu.
PROHIBITED_MENU_COMMANDS = frozenset(
    {
        "sell",
        "sellall",
        "stop",
        "papermode",
        "golive",
        "confirm",
        "tp",
        "sl",
        "strict",
        "loose",
        "setbuysol",
        "research",
        "pending",
        "approve",
        "reject",
    }
)


async def sync_owner_command_menu(call: TelegramCall) -> None:
    """Replace Telegram's persisted bot command menu with Edge Lab's safe menu."""

    commands = [dict(item) for item in OWNER_COMMAND_MENU]
    names = {item["command"] for item in commands}
    forbidden = names & PROHIBITED_MENU_COMMANDS
    if forbidden:
        raise RuntimeError(f"refusing prohibited Telegram menu commands: {sorted(forbidden)}")
    await call("setMyCommands", {"commands": commands})
