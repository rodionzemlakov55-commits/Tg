"""Случайное определение минут до следующей отправки сообщения.

Идея: чтобы бот писал не строго "по расписанию на ровную минуту",
а как живой человек, к основному интервалу (в часах) прибавляется
случайная задержка от 1 до 30 минут.
"""

import random


def random_minutes(max_minutes: int = 30, min_minutes: int = 1) -> int:
    """
    Возвращает случайное целое число минут в диапазоне
    [min_minutes, max_minutes].

    min_minutes и max_minutes - включаются в диапазон.
    """
    if min_minutes > max_minutes:
        min_minutes = max_minutes
    return random.randint(min_minutes, max_minutes)


def random_seconds(max_minutes: int = 30, min_minutes: int = 1) -> int:
    """Случайная задержка в секундах (по умолчанию 1..30 минут)."""
    return random_minutes(max_minutes, min_minutes) * 60


def next_delay_seconds(hours: float, max_minutes: int = 30) -> int:
    """
    Полный интервал (в секундах) до следующей отправки:

        interval = hours * 3600 + случайные минуты (1..max_minutes)

    Например: hours=1, случайные 12 минут -> 1ч12м = 4320 секунд.
    """
    return int(hours * 3600) + random_seconds(max_minutes)
