"""Точка входа консольного интерфейса DuckBot."""

from __future__ import annotations

import argparse
import logging
import sys

from duckbot.app.runner import DuckBotRunner
from duckbot.config import load_settings
from duckbot.exceptions import ConfigurationError, DuckBotError
from duckbot.support.logging_setup import configure_logging


class RussianArgumentParser(argparse.ArgumentParser):
    """Парсер аргументов с русскоязычными заголовками."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = "позиционные аргументы"
        self._optionals.title = "опции"
        self.add_argument("-h", "--help", action="help", help="Показать эту справку и выйти.")

    def format_usage(self) -> str:
        """Возвращает строку использования с русским префиксом."""
        return super().format_usage().replace("usage:", "использование:", 1)

    def format_help(self) -> str:
        """Возвращает справку с русским префиксом строки использования."""
        return super().format_help().replace("usage:", "использование:", 1)


def build_parser() -> argparse.ArgumentParser:
    parser = RussianArgumentParser(
        prog="duckbot",
        description="Консольная утилита для автоматизации DuckMyDuck.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Путь к основному конфигу (по умолчанию: config.yaml).",
    )
    parser.add_argument(
        "--profiles-file",
        default="profiles.local.yaml",
        help="Путь к файлу профилей (по умолчанию: profiles.local.yaml).",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="команды",
        parser_class=RussianArgumentParser,
    )

    auth_check = subparsers.add_parser("auth-check", help="Проверить авторизацию профиля.")
    auth_check.add_argument("--profile", required=True, help="Имя профиля для проверки.")

    once = subparsers.add_parser("once", help="Выполнить один цикл по профилям.")
    once_group = once.add_mutually_exclusive_group()
    once_group.add_argument("--profile", help="Выполнить цикл только для одного профиля.")
    once_group.add_argument("--all", action="store_true", help="Запустить все включенные профили.")

    run = subparsers.add_parser("run", help="Запустить бесконечный рабочий цикл.")
    run_group = run.add_mutually_exclusive_group()
    run_group.add_argument("--profile", help="Запустить рабочий цикл только для одного профиля.")
    run_group.add_argument("--all", action="store_true", help="Запустить все включенные профили.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config, args.profiles_file)
    except ConfigurationError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 1

    configure_logging(settings.app.logging)
    runner = DuckBotRunner(settings)

    try:
        if args.command == "auth-check":
            runner.auth_check(runner.resolve_profiles(profile_name=args.profile))
            return 0

        if args.command == "once":
            runner.run_once(
                runner.resolve_profiles(
                    profile_name=args.profile,
                    all_profiles=args.all,
                )
            )
            return 0

        if args.command == "run":
            runner.run_forever(
                runner.resolve_profiles(
                    profile_name=args.profile,
                    all_profiles=args.all,
                )
            )
            return 0

        parser.error(f"Неизвестная команда: {args.command}")
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Остановлено пользователем", extra={"profile": "-"})
        return 0
    except DuckBotError as exc:
        logging.getLogger(__name__).error("DuckBot завершился с ошибкой: %s", exc, extra={"profile": "-"})
        return 1
    except Exception as exc:  # pragma: no cover - защитная ветка
        logging.getLogger(__name__).exception("Непредвиденная ошибка: %s", exc, extra={"profile": "-"})
        return 1

    return 0
