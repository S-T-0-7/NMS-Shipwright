"""Player currencies inside a deobfuscated save JSON tree."""
from __future__ import annotations

PLAYER_PATH = ("BaseContext", "PlayerStateData")
CURRENCIES = {"units": "Units", "nanites": "Nanites", "quicksilver": "Specials"}
MAX_VALUE = 2 ** 31 - 1  # stored as signed 32-bit


def _state(readable_json: dict) -> dict:
    return readable_json[PLAYER_PATH[0]][PLAYER_PATH[1]]


def get_currencies(readable_json: dict) -> dict:
    state = _state(readable_json)
    return {name: int(state.get(key, 0)) for name, key in CURRENCIES.items()}


def set_currencies(readable_json: dict, **values: int) -> dict:
    """Set any of units / nanites / quicksilver; returns the new values."""
    state = _state(readable_json)
    for name, value in values.items():
        if name not in CURRENCIES:
            raise ValueError(f"unknown currency {name!r}")
        value = int(value)
        if not 0 <= value <= MAX_VALUE:
            raise ValueError(f"{name} must be between 0 and {MAX_VALUE:,}")
        state[CURRENCIES[name]] = value
    return get_currencies(readable_json)


def primary_ship(readable_json: dict) -> int:
    return int(_state(readable_json).get("PrimaryShip", 0))
