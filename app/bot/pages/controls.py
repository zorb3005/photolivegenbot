from app.bot.ui import ikb_rows


def control_kb(prefix: str):
    """
    Минимальная inline-клавиатура для регуляторов.
    Всего три кнопки: Назад (шаг -1), Сохранить (закрыть), Вперёд (шаг +1).
    """
    return ikb_rows([
        [
            ("⬅️ Назад", f"{prefix}:prev"),
            ("✅ Сохранить", f"{prefix}:save"),
            ("➡️ Вперёд", f"{prefix}:next"),
        ],
    ])


def shift(value: int, delta: int) -> int:
    """Сдвиг значения в диапазоне 1..7."""
    return max(1, min(7, value + delta))
