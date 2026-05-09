"""Сохранение состояния выполнения."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ProfileRuntimeState(BaseModel):
    """Кэшированное состояние одного профиля."""

    model_config = ConfigDict(extra="ignore")

    token: str | None = None
    token_exp: int | None = None
    last_auth_at: int | None = None
    player_id: int | None = None
    account_id: int | None = None
    player_name: str | None = None


class RuntimeStateStore:
    """Хранилище состояния профилей на основе JSON-файла."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._states: dict[str, ProfileRuntimeState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._states = {}
            return

        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        raw_states = payload.get("profiles", {}) if isinstance(payload, dict) else {}
        self._states = {
            profile_name: ProfileRuntimeState.model_validate(data)
            for profile_name, data in raw_states.items()
            if isinstance(profile_name, str)
        }

    def get(self, profile_name: str) -> ProfileRuntimeState:
        return self._states.get(profile_name, ProfileRuntimeState())

    def save(self, profile_name: str, state: ProfileRuntimeState) -> ProfileRuntimeState:
        self._states[profile_name] = state
        self._flush()
        return state

    def update(self, profile_name: str, **fields: object) -> ProfileRuntimeState:
        state = self.get(profile_name).model_copy(update=fields)
        return self.save(profile_name, state)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profiles": {
                profile_name: state.model_dump(exclude_none=True)
                for profile_name, state in self._states.items()
            }
        }
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
