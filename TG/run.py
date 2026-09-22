"""Точка входа бота.

Читает System/Config.yaml, настраивает логирование
(Logs/Info.log, Logs/Error.log) и запускает бота.

Запуск:
    .venv/bin/python run.py
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

from Logic.My_tg import MyTgBot

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "Logs"
CONFIG_PATH = BASE_DIR / "System" / "Config.yaml"


def setup_logging() -> None:
    """Настраивает логирование в файлы Info.log / Error.log и в консоль."""
    LOGS_DIR.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    info_handler = RotatingFileHandler(
        LOGS_DIR / "Info.log", maxBytes=5 * 1024 * 1024,
        backupCount=3, encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)

    error_handler = RotatingFileHandler(
        LOGS_DIR / "Error.log", maxBytes=5 * 1024 * 1024,
        backupCount=3, encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(info_handler)
    root.addHandler(error_handler)
    root.addHandler(stream)


def load_config() -> dict:
    """Читает конфигурацию из YAML."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def main() -> None:
    setup_logging()
    logger = logging.getLogger("run")

    config = load_config()
    logger.info("Конфиг загружен: %s", CONFIG_PATH)

    bot = MyTgBot(config)
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем (Ctrl+C).")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("run").critical("Критическая ошибка: %s", exc, exc_info=True)
