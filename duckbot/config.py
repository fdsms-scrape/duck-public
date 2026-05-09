"""Загрузка и валидация конфигурации."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from duckbot.constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_EGG_MERGE_LIMITS,
    DEFAULT_FEED_LIMITS,
    DEFAULT_HTTP_HEADERS,
)
from duckbot.exceptions import ConfigurationError


def _normalize_url(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("URL не может быть пустым.")
    return normalized.rstrip("/")


def _normalize_quality(value: object) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("Редкость не может быть пустой.")
    return normalized


def _normalize_level(value: object, *, field_name: str) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} должен быть целым числом.") from exc
    if level < 1:
        raise ValueError(f"{field_name} должен быть не меньше 1.")
    return level


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    file_path: str = "logs/duckbot.log"
    max_bytes: int = 1_048_576
    backup_count: int = 3
    console: bool = True


class RetrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    rate_limit_multiplier: float = 5.0


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_margin_seconds: int = 300
    state_path: str = "runtime/state.json"


class FeatureSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_eggs: bool = False
    participate_egg_tournaments: bool = True
    collect_alert_rewards: bool = True
    collect_task_rewards: bool = True
    collect_custom_task_rewards: bool = False
    collect_reward_pass_rewards: bool = True
    inspect_tournaments: bool = True
    inspect_clan_show: bool = True
    use_clan_show_sabotages: bool = False


class BreedRuleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: str
    min_level: int = 1
    max_level: int | None = None
    currency: str = "corn"
    enabled: bool = True

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, value: str) -> str:
        return _normalize_quality(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Валюта для правила скрещивания не может быть пустой.")
        return normalized

    @field_validator("min_level")
    @classmethod
    def validate_min_level(cls, value: int) -> int:
        return _normalize_level(value, field_name="Минимальный уровень для скрещивания")

    @field_validator("max_level")
    @classmethod
    def validate_max_level(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return _normalize_level(value, field_name="Максимальный уровень для скрещивания")

    @model_validator(mode="after")
    def validate_level_range(self) -> "BreedRuleSettings":
        if self.max_level is not None and self.min_level > self.max_level:
            raise ValueError("Минимальный уровень правила скрещивания не может быть больше максимального.")
        return self


class FeedRuleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: str
    min_level: int = 1
    max_level: int | None = None
    max_cost: int
    enabled: bool = True

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, value: str) -> str:
        return _normalize_quality(value)

    @field_validator("min_level")
    @classmethod
    def validate_min_level(cls, value: int) -> int:
        return _normalize_level(value, field_name="Минимальный уровень для кормления")

    @field_validator("max_level")
    @classmethod
    def validate_max_level(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return _normalize_level(value, field_name="Максимальный уровень для кормления")

    @field_validator("max_cost")
    @classmethod
    def validate_max_cost(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Максимальная стоимость кормления не может быть отрицательной.")
        return value

    @model_validator(mode="after")
    def validate_level_range(self) -> "FeedRuleSettings":
        if self.max_level is not None and self.min_level > self.max_level:
            raise ValueError("Минимальный уровень правила кормления не может быть больше максимального.")
        return self


def _expand_compact_feed_rules(raw_rules: Mapping[object, object]) -> list[dict[str, Any]]:
    expanded_rules: list[dict[str, Any]] = []
    for quality_key, quality_value in raw_rules.items():
        quality = _normalize_quality(quality_key)

        if isinstance(quality_value, list):
            for index, level_value in enumerate(quality_value, start=1):
                if level_value is None:
                    continue
                if isinstance(level_value, Mapping):
                    payload = dict(level_value)
                    payload.setdefault("min_level", index)
                    payload.setdefault("max_level", index)
                    payload["quality"] = quality
                    expanded_rules.append(payload)
                    continue
                expanded_rules.append(
                    {
                        "quality": quality,
                        "min_level": index,
                        "max_level": index,
                        "max_cost": level_value,
                    }
                )
            continue

        if isinstance(quality_value, Mapping):
            for level_key, level_value in quality_value.items():
                level = _normalize_level(level_key, field_name="Уровень для компактного правила кормления")
                if isinstance(level_value, Mapping):
                    payload = dict(level_value)
                    payload.setdefault("min_level", level)
                    payload.setdefault("max_level", level)
                    payload["quality"] = quality
                    expanded_rules.append(payload)
                    continue
                expanded_rules.append(
                    {
                        "quality": quality,
                        "min_level": level,
                        "max_level": level,
                        "max_cost": level_value,
                    }
                )
            continue

        raise ValueError("Компактные feed_rules должны быть списком уровней или словарем по уровням.")

    return expanded_rules


def _expand_compact_breed_rules(raw_rules: Mapping[object, object]) -> list[dict[str, Any]]:
    expanded_rules: list[dict[str, Any]] = []
    for quality_key, quality_value in raw_rules.items():
        quality = _normalize_quality(quality_key)

        if isinstance(quality_value, list):
            levels = quality_value
            payload: dict[str, Any] = {"quality": quality, "currency": "corn", "enabled": True}
        elif isinstance(quality_value, Mapping):
            payload = dict(quality_value)
            levels = payload.pop("levels", None)
            if levels is None:
                raise ValueError("Компактные breed_rules должны содержать поле `levels`.")
            payload["quality"] = quality
        else:
            raise ValueError("Компактные breed_rules должны быть списком уровней или объектом с полем `levels`.")

        if not isinstance(levels, list) or not levels:
            raise ValueError("Поле `levels` в compact breed_rules должно быть непустым списком.")

        for level_value in levels:
            level = _normalize_level(level_value, field_name="Уровень для компактного правила скрещивания")
            expanded_rules.append(
                {
                    **payload,
                    "quality": quality,
                    "min_level": level,
                    "max_level": level,
                }
            )

    return expanded_rules


class GameSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_merge_slot: int = 25
    egg_merge_limits: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_EGG_MERGE_LIMITS))
    clan_show_log_best_targets_limit: int = 3
    clan_show_log_recent_attacks_limit: int = 3
    clan_show_attack_limit_per_cycle: int = 1
    clan_show_attack_min_success_chance: float = 0.75
    clan_show_attack_max_revenge_chance: float = 0.60
    clan_show_attack_require_same_group: bool = True
    clan_show_attack_refresh_targets_each_use: bool = True
    feed_limits: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_FEED_LIMITS))
    feed_rules: list[FeedRuleSettings] = Field(default_factory=list)
    breed_rules: list[BreedRuleSettings] = Field(default_factory=lambda: [BreedRuleSettings(quality="COMMON")])

    @field_validator("egg_merge_limits", mode="before")
    @classmethod
    def normalize_egg_merge_limits(cls, value: object) -> object:
        if value is None:
            return dict(DEFAULT_EGG_MERGE_LIMITS)
        return value

    @field_validator("egg_merge_limits")
    @classmethod
    def validate_egg_merge_limits(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for egg_type, max_level in value.items():
            normalized_type = str(egg_type).strip().upper()
            if not normalized_type:
                raise ValueError("Тип яйца в egg_merge_limits не может быть пустым.")
            normalized[normalized_type] = _normalize_level(
                max_level,
                field_name=f"Максимальный уровень merge для яйца {normalized_type}",
            )
        return normalized

    @field_validator(
        "clan_show_log_best_targets_limit",
        "clan_show_log_recent_attacks_limit",
        "clan_show_attack_limit_per_cycle",
    )
    @classmethod
    def validate_positive_integer_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Значение должно быть не меньше 1.")
        return value

    @field_validator(
        "clan_show_attack_min_success_chance",
        "clan_show_attack_max_revenge_chance",
    )
    @classmethod
    def validate_probability_settings(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("Вероятность должна быть в диапазоне от 0 до 1.")
        return value

    @field_validator("feed_rules", mode="before")
    @classmethod
    def normalize_feed_rules(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return _expand_compact_feed_rules(value)
        return value

    @field_validator("breed_rules", mode="before")
    @classmethod
    def normalize_breed_rules(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return _expand_compact_breed_rules(value)
        return value

    @model_validator(mode="after")
    def populate_feed_rules_from_limits(self) -> "GameSettings":
        if not self.feed_rules:
            self.feed_rules = [
                FeedRuleSettings(quality=quality, max_cost=max_cost)
                for quality, max_cost in self.feed_limits.items()
            ]
        return self


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_base_url: str = DEFAULT_API_BASE_URL
    request_timeout_seconds: float = 15.0
    cycle_sleep_seconds: int = 1800
    between_profiles_delay_seconds: list[float] = Field(default_factory=lambda: [5.0, 10.0])
    between_actions_delay_seconds: list[float] = Field(default_factory=lambda: [0.5, 1.0])
    after_feed_delay_seconds: list[float] = Field(default_factory=lambda: [1.0, 2.0])
    after_egg_merge_delay_seconds: list[float] = Field(default_factory=lambda: [1.0, 2.0])
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    features: FeatureSettings = Field(default_factory=FeatureSettings)
    game: GameSettings = Field(default_factory=GameSettings)
    http_headers: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_HTTP_HEADERS))

    @field_validator("api_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _normalize_url(value)

    @field_validator(
        "between_profiles_delay_seconds",
        "between_actions_delay_seconds",
        "after_feed_delay_seconds",
        "after_egg_merge_delay_seconds",
    )
    @classmethod
    def validate_delay_range(cls, value: list[float]) -> list[float]:
        if len(value) != 2:
            raise ValueError("Диапазон задержки должен содержать ровно два значения.")
        minimum, maximum = value
        if minimum < 0 or maximum < 0:
            raise ValueError("Задержки не могут быть отрицательными.")
        if minimum > maximum:
            raise ValueError("Минимальная задержка не может быть больше максимальной.")
        return value


class ProfileSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True
    api_base_url: str | None = None
    webapp_url: str | None = None
    init_data: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Имя профиля не может быть пустым.")
        return normalized

    @field_validator("api_base_url")
    @classmethod
    def validate_profile_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_url(value)

    @model_validator(mode="after")
    def validate_auth_sources(self) -> "ProfileSettings":
        sources = [self.webapp_url, self.init_data]
        provided_count = sum(1 for item in sources if item and item.strip())
        if provided_count != 1:
            raise ValueError(
                "У профиля должен быть указан ровно один источник авторизации: "
                "`webapp_url` или `init_data`."
            )
        return self


class ProfilesDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[ProfileSettings]


@dataclass(slots=True)
class ProjectSettings:
    app: AppSettings
    profiles: list[ProfileSettings]
    config_path: Path
    profiles_path: Path

    def enabled_profiles(self) -> list[ProfileSettings]:
        return [profile for profile in self.profiles if profile.enabled]

    def get_profile(self, profile_name: str) -> ProfileSettings:
        for profile in self.profiles:
            if profile.name == profile_name:
                return profile
        raise ConfigurationError(f"Профиль `{profile_name}` не найден.")


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        example_name = f"{path.stem}.example{path.suffix}"
        raise ConfigurationError(
            f"Файл `{path}` не найден. Создайте его на основе `{example_name}`."
        )

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ConfigurationError(f"Файл `{path}` должен содержать YAML-объект верхнего уровня.")

    return data


def load_settings(
    config_path: str | Path = "config.yaml",
    profiles_path: str | Path = "profiles.local.yaml",
) -> ProjectSettings:
    resolved_config_path = Path(config_path)
    resolved_profiles_path = Path(profiles_path)

    try:
        app_settings = AppSettings.model_validate(_read_yaml_file(resolved_config_path))
        profiles_document = ProfilesDocument.model_validate(_read_yaml_file(resolved_profiles_path))
    except ValidationError as exc:
        raise ConfigurationError(f"Ошибка валидации конфигурации: {exc}") from exc

    seen_names: set[str] = set()
    for profile in profiles_document.profiles:
        if profile.name in seen_names:
            raise ConfigurationError(f"Профиль `{profile.name}` объявлен больше одного раза.")
        seen_names.add(profile.name)

    if not profiles_document.profiles:
        raise ConfigurationError("В `profiles.local.yaml` должен быть хотя бы один профиль.")

    return ProjectSettings(
        app=app_settings,
        profiles=profiles_document.profiles,
        config_path=resolved_config_path,
        profiles_path=resolved_profiles_path,
    )
