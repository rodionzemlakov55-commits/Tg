"""Логика Telegram-бота через MTProto (библиотека Telethon).

Бот читает список сообщений из файлов {texts_dir}/{язык}.txt
(ru.txt, en.txt) и рассылает их в указанные группы через интервалы
(в часах), к каждому интервалу прибавляя случайную задержку 1..30 минут.
Сообщение отправляется ЦЕЛИКОМ, одним куском, без дробления.

API_ID, API_HASH и SESSION_STRING читаются из переменных окружения
(для хостинга). Если их нет — API_ID/API_HASH берутся из Config.yaml,
а сессия — из файла {session_name}.session.

Настройки групп, языка, прокси — в Config.yaml.
"""

import asyncio
import logging
import os
import random
from pathlib import Path

from telethon import TelegramClient, connection
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from Logic.ranminut import next_delay_seconds

logger = logging.getLogger("tg_bot")

# Дефолтная папка с текстами
DEFAULT_TEXTS_DIR = Path(__file__).resolve().parent.parent / "Data" / "Textgroup"

# Допустимые языки текстов
SUPPORTED_LANGS = ("ru", "en")

# Лимит Telegram на длину одного сообщения
TG_MAX_LEN = 4096


class MyTgBot:
    """Бот рассылки сообщений в группы Telegram через MTProto."""

    def __init__(self, config: dict):
        # --- API_ID / API_HASH: сначала env, потом Config.yaml ---
        env_api_id = os.getenv("API_ID", "").strip()
        env_api_hash = os.getenv("API_HASH", "").strip()

        raw_api_id = env_api_id or str(config.get("api_id", "") or "")
        self.api_id = int(raw_api_id) if raw_api_id else 0
        self.api_hash = env_api_hash or (config.get("api_hash") or "").strip()

        self.phone = (config.get("phone") or "").strip()

        # --- SESSION_STRING из env ---
        self.session_string = os.getenv("SESSION_STRING", "").strip()
        self.session_name = config.get("session_name", "session")

        # --- Папка с текстами ---
        texts_dir = (config.get("texts_dir") or "").strip()
        if texts_dir:
            self.texts_dir = Path(texts_dir).expanduser().resolve()
        else:
            self.texts_dir = DEFAULT_TEXTS_DIR
        logger.info("Папка с текстами: %s", self.texts_dir)

        # --- Язык по умолчанию ---
        self.default_language = (config.get("language") or "ru").strip().lower()
        if self.default_language not in SUPPORTED_LANGS:
            raise RuntimeError(
                f"Неизвестный язык по умолчанию: {self.default_language!r}. "
                f"Допустимые значения: {', '.join(SUPPORTED_LANGS)}"
            )

        # {username: {"time": hours, "language": "ru"}}
        self.groups = config.get("groups", {})

        # --- Какие языки нужны ---
        needed_langs = {self.default_language}
        for username, cfg in self.groups.items():
            lang = (cfg.get("language") or self.default_language).strip().lower()
            if lang not in SUPPORTED_LANGS:
                raise RuntimeError(
                    f"Неизвестный язык у группы {username}: {lang!r}. "
                    f"Допустимые значения: {', '.join(SUPPORTED_LANGS)}"
                )
            needed_langs.add(lang)

        # --- Загружаем тексты ---
        self.messages_by_lang: dict = {}
        for lang in needed_langs:
            self.messages_by_lang[lang] = self._load_messages(lang)

        if self.api_id <= 0 or not self.api_hash:
            raise RuntimeError(
                "Пустой api_id / api_hash. Задайте их через переменные "
                "окружения API_ID и API_HASH или в System/Config.yaml "
                "(данные берутся на https://my.telegram.org/apps)"
            )

        # --- Параметры клиента ---
        client_kwargs = self._build_client_kwargs(config)

        # --- Сессия: StringSession из env или файл ---
        if self.session_string:
            session = StringSession(self.session_string)
            logger.info("Используется StringSession из переменной окружения")
        else:
            session = self.session_name
            logger.info("Используется файловая сессия: %s.session", self.session_name)

        self.client = TelegramClient(
            session,
            self.api_id,
            self.api_hash,
            **client_kwargs,
        )

    # ------------------------------------------------------------------
    #  Прокси / таймауты
    # ------------------------------------------------------------------
    def _build_client_kwargs(self, config: dict) -> dict:
        kwargs: dict = {}

        kwargs["timeout"] = int(config.get("timeout", 30))
        kwargs["connection_retries"] = int(config.get("connection_retries", 10))
        kwargs["retry_delay"] = int(config.get("retry_delay", 5))

        proxy_cfg = config.get("proxy") or {}
        proxy_type = (proxy_cfg.get("type") or "none").strip().lower()

        if proxy_type in ("none", "", "off", "disabled"):
            logger.info("Прокси не используется (прямое подключение)")
            return kwargs

        host = str(proxy_cfg.get("host") or "").strip()
        port = int(proxy_cfg.get("port") or 0)
        if not host or port <= 0:
            raise RuntimeError("В секции `proxy` Config.yaml не указаны host/port")

        if proxy_type in ("mtproxy", "mtproto", "mt"):
            secret = str(proxy_cfg.get("secret") or "").strip()
            if not secret:
                raise RuntimeError("Для MTProto-прокси нужно указать `secret`")

            if secret.lower().startswith("ee"):
                try:
                    import TelethonFakeTLS  # type: ignore
                except ImportError as e:
                    raise RuntimeError(
                        "Секрет начинается с 'ee' (FakeTLS). Установите "
                        "TelethonFakeTLS: pip install TelethonFakeTLS"
                    ) from e
                kwargs["connection"] = TelethonFakeTLS.ConnectionTcpMTProxyFakeTLS
                kwargs["proxy"] = (host, port, secret[2:])
                logger.info("MTProto(FakeTLS)-прокси: %s:%s", host, port)
                return kwargs

            kwargs["connection"] = connection.ConnectionTcpMTProxyRandomizedIntermediate
            kwargs["proxy"] = (host, port, secret)
            logger.info("MTProto-прокси: %s:%s", host, port)
            return kwargs

        if proxy_type in ("socks5", "socks", "http"):
            try:
                import socks  # PySocks
            except ImportError as e:
                raise RuntimeError(
                    "Для SOCKS5/HTTP установите PySocks: pip install PySocks"
                ) from e

            user = proxy_cfg.get("user") or None
            password = proxy_cfg.get("password") or None
            kind = socks.SOCKS5 if proxy_type in ("socks5", "socks") else socks.HTTP

            if user:
                kwargs["proxy"] = (kind, host, port, True, user, password)
            else:
                kwargs["proxy"] = (kind, host, port)
            logger.info("%s-прокси: %s:%s", proxy_type.upper(), host, port)
            return kwargs

        raise RuntimeError(f"Неизвестный тип прокси: {proxy_type!r}")

    # ------------------------------------------------------------------
    #  Загрузка сообщений
    # ------------------------------------------------------------------
    def _load_messages(self, language: str) -> list:
        text_file = self.texts_dir / f"{language}.txt"
        if not text_file.exists():
            logger.warning("Файл с сообщениями не найден: %s", text_file)
            return []
        raw = text_file.read_text(encoding="utf-8")
        messages = [block.strip() for block in raw.split("\n\n") if block.strip()]
        logger.info(
            "Загружено сообщений: %d (язык: %s, файл: %s)",
            len(messages), language, text_file,
        )
        return messages

    # ------------------------------------------------------------------
    #  Запуск
    # ------------------------------------------------------------------
    async def run(self) -> None:
        if not self.groups:
            raise RuntimeError("В Config.yaml не указаны группы (раздел groups)")

        for username, cfg in self.groups.items():
            lang = (cfg.get("language") or self.default_language).strip().lower()
            if not self.messages_by_lang.get(lang):
                raise RuntimeError(
                    f"Для группы {username} (язык: {lang}) нет сообщений. "
                    f"Заполните {self.texts_dir / (lang + '.txt')}"
                )

        # --- Подключение / авторизация ---
        if self.session_string:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                raise RuntimeError(
                    "StringSession не авторизован. Сгенерируйте SESSION_STRING заново."
                )
        else:
            await self.client.start(phone=self.phone)

        me = await self.client.get_me()
        logger.info("Бот авторизован как: %s", me.username or me.first_name)

        tasks = [
            self._group_loop(username, cfg)
            for username, cfg in self.groups.items()
        ]
        logger.info("Запущено циклов рассылки: %d", len(tasks))
        await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    #  Цикл рассылки
    # ------------------------------------------------------------------
    async def _group_loop(self, username: str, cfg: dict) -> None:
        hours = float(cfg.get("time", 1))
        lang = (cfg.get("language") or self.default_language).strip().lower()
        messages = self.messages_by_lang[lang]

        while True:
            try:
                delay = next_delay_seconds(hours)
                logger.info(
                    "Группа %s | язык: %s | следующая отправка через ~%.1f мин",
                    username, lang, delay / 60,
                )
                await asyncio.sleep(delay)

                message = random.choice(messages)
                await self._send_human_like(username, message)
            except FloodWaitError as e:
                logger.warning("Группа %s | флуд-контроль: ждём %s сек",
                               username, e.seconds)
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:  # noqa: BLE001
                logger.error("Группа %s | ошибка: %s", username, e, exc_info=True)
                await asyncio.sleep(60)

    # ------------------------------------------------------------------
    #  Отправка одним сообщением
    # ------------------------------------------------------------------
    async def _send_human_like(self, username: str, text: str) -> None:
        entity = await self.client.get_input_entity(username)

        text = " ".join(text.split()).strip()
        if not text:
            return

        if len(text) > TG_MAX_LEN:
            logger.warning("Группа %s | текст длиннее %d, обрезаю",
                           username, TG_MAX_LEN)
            text = text[:TG_MAX_LEN]

        await asyncio.sleep(random.uniform(0.8, 2.5))

        pause = min(len(text) / 50.0, 8.0) + random.uniform(0.5, 1.5)
        logger.info("Группа %s | печатает ~%s сек...", username, round(pause, 1))
        async with self.client.action(entity, "typing"):
            await asyncio.sleep(pause)

        await self.client.send_message(entity, text)
        logger.info("Группа %s | сообщение отправлено (%d символов)",
                    username, len(text))
