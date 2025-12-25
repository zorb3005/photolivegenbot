from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Tuple, List

from sqlalchemy import text

from app.bot.admin.live_metrics import get_active_generations, get_online_user_ids
from app.infrastructure.db.base import async_session
from app.settings import settings


@dataclass(frozen=True)
class RecentRequest:
    timestamp: datetime
    user_id: int
    segment: str | None
    generation_type: str | None
    status: str | None


@dataclass(frozen=True)
class AdminStats:
    total_users: int
    active_today: int
    generations_total: int
    generations_today: int
    spent_today: int
    payments_total: Decimal
    payments_today: Decimal
    online_now: int
    online_clients: int
    online_non_clients: int
    active_generations: int
    active_generation_users: int
    active_generation_clients: int
    active_generation_non_clients: int
    active_generations_by_type: Dict[str, int]
    active_generations_by_provider: Dict[str, int]
    test_payments_count: int
    test_payments_total: Decimal
    real_payments_count: int
    real_payments_total: Decimal
    api_costs_today: Dict[str, Tuple[int, Decimal, Decimal]]
    last_requests: List[RecentRequest]
    segments: Dict[str, Tuple[int, float]]


def _fmt_int(val: int) -> str:
    return f"{int(val):,}".replace(",", " ")


def _fmt_money(val: Decimal) -> str:
    quantized = val.quantize(Decimal("0.01"))
    return f"{quantized:,.2f}".replace(",", " ")


def _fmt_usd(val: Decimal) -> str:
    quantized = val.quantize(Decimal("0.01"))
    return f"{quantized:,.2f}".replace(",", " ")


async def fetch_admin_stats() -> AdminStats:
    today = date.today()
    async with async_session() as s:
        total_users = int(await s.scalar(text("SELECT COUNT(*) FROM users")) or 0)
        active_today = int(
            await s.scalar(
                text(
                    "SELECT COUNT(DISTINCT user_id) FROM generation_history "
                    "WHERE status = 'succeeded' AND DATE(timestamp) = :today"
                ),
                {"today": today},
            )
            or 0
        )
        generations_total = int(
            await s.scalar(
                text("SELECT COUNT(*) FROM generation_history WHERE status = 'succeeded'")
            )
            or 0
        )
        generations_today = int(
            await s.scalar(
                text(
                    "SELECT COUNT(*) FROM generation_history "
                    "WHERE status = 'succeeded' AND DATE(timestamp) = :today"
                ),
                {"today": today},
            )
            or 0
        )
        spent_today = int(
            await s.scalar(
                text(
                    "SELECT COALESCE(SUM(cost), 0) FROM generation_history "
                    "WHERE status = 'succeeded' AND DATE(timestamp) = :today"
                ),
                {"today": today},
            )
            or 0
        )
        payments_total = Decimal(
            await s.scalar(
                text("SELECT COALESCE(SUM(rub_amount), 0) FROM payments WHERE status = 'succeeded'")
            )
            or 0
        )
        payments_today = Decimal(
            await s.scalar(
                text(
                    """
                    SELECT COALESCE(SUM(rub_amount), 0)
                      FROM payments
                     WHERE status = 'succeeded'
                       AND DATE(COALESCE(completed_at, updated_at, created_at)) = :today
                    """
                ),
                {"today": today},
            )
            or 0
        )
        test_real = await s.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE COALESCE((metadata->>'_test')::boolean, false) = true) AS test_cnt,
                    COALESCE(SUM(rub_amount) FILTER (WHERE COALESCE((metadata->>'_test')::boolean, false) = true), 0) AS test_sum,
                    COUNT(*) FILTER (WHERE COALESCE((metadata->>'_test')::boolean, false) = false) AS real_cnt,
                    COALESCE(SUM(rub_amount) FILTER (WHERE COALESCE((metadata->>'_test')::boolean, false) = false), 0) AS real_sum
                  FROM payments
                 WHERE status = 'succeeded'
                """
            )
        )
        row = test_real.mappings().first() or {}
        test_payments_count = int(row.get("test_cnt") or 0)
        test_payments_total = Decimal(row.get("test_sum") or 0)
        real_payments_count = int(row.get("real_cnt") or 0)
        real_payments_total = Decimal(row.get("real_sum") or 0)
        rows = await s.execute(text("SELECT segment, COUNT(*) AS cnt FROM users GROUP BY segment"))
        raw = {str(row.segment): int(row.cnt) for row in rows if getattr(row, "segment", None)}
        lead_cnt = total_users
        client_cnt = raw.get("client", 0)
        qual_cnt = raw.get("qual", 0) + client_cnt  # qual + client, по требованиям маркетинга

        def _pct(cnt: int) -> float:
            return round((cnt / total_users) * 100, 1) if total_users else 0.0

        segments: Dict[str, Tuple[int, float]] = {
            "lead": (lead_cnt, _pct(lead_cnt)),
            "qual": (qual_cnt, _pct(qual_cnt)),
            "client": (client_cnt, _pct(client_cnt)),
        }

        def _to_decimal(raw: str) -> Decimal:
            try:
                return Decimal(str(raw))
            except (InvalidOperation, ValueError, TypeError):
                return Decimal("0")

        usd_rate = _to_decimal(settings.USD_RATE_RUB)
        kling_usd = _to_decimal(settings.KLINGAI_COST_USD)

        rows = await s.execute(
            text(
                """
                SELECT generation_type, COUNT(*) AS cnt
                  FROM generation_history
                 WHERE status = 'succeeded' AND DATE(timestamp) = :today
                 GROUP BY generation_type
                """
            ),
            {"today": today},
        )
        mapped = rows.mappings().all()
        counts_today = {str(r["generation_type"]): int(r["cnt"]) for r in mapped if r.get("generation_type")}
        kling_count = counts_today.get("animate_photo", 0)
        kling_cost_usd = kling_usd * kling_count
        api_costs_today: Dict[str, Tuple[int, Decimal, Decimal]] = {
            "klingai": (kling_count, kling_cost_usd * usd_rate, kling_cost_usd),
        }

        rows = await s.execute(
            text(
                """
                SELECT gh.timestamp, gh.user_id, gh.generation_type, gh.status, u.segment
                  FROM generation_history gh
                  LEFT JOIN users u ON u.telegram_id = gh.user_id
                 ORDER BY gh.timestamp DESC
                 LIMIT 10
                """
            )
        )
        last_requests = []
        for row in rows.mappings().all():
            last_requests.append(
                RecentRequest(
                    timestamp=row["timestamp"],
                    user_id=int(row["user_id"]),
                    segment=str(row["segment"]) if row.get("segment") else None,
                    generation_type=str(row["generation_type"]) if row.get("generation_type") else None,
                    status=str(row["status"]) if row.get("status") else None,
                )
            )

        online_ids = get_online_user_ids(within_seconds=60)
        active_generations = get_active_generations()
        active_generation_users = {g.user_id for g in active_generations}
        all_active_ids = set(online_ids) | active_generation_users
        segments_map: Dict[int, str] = {}
        if all_active_ids:
            rows = await s.execute(
                text("SELECT telegram_id, segment FROM users WHERE telegram_id = ANY(:ids)"),
                {"ids": list(all_active_ids)},
            )
            segments_map = {
                int(row.telegram_id): str(row.segment) for row in rows if getattr(row, "segment", None)
            }

        def _count_clients(ids: set[int] | list[int]) -> tuple[int, int]:
            total = len(ids)
            clients = sum(1 for uid in ids if segments_map.get(int(uid)) == "client")
            return clients, max(0, total - clients)

        online_clients, online_non_clients = _count_clients(online_ids)
        active_clients, active_non_clients = _count_clients(active_generation_users)

        active_by_type: Dict[str, int] = {}
        active_by_provider: Dict[str, int] = {}
        for gen in active_generations:
            if gen.generation_type:
                active_by_type[gen.generation_type] = active_by_type.get(gen.generation_type, 0) + 1
            if gen.provider:
                active_by_provider[gen.provider] = active_by_provider.get(gen.provider, 0) + 1
    return AdminStats(
        total_users=total_users,
        active_today=active_today,
        generations_total=generations_total,
        generations_today=generations_today,
        spent_today=spent_today,
        payments_total=payments_total,
        payments_today=payments_today,
        online_now=len(online_ids),
        online_clients=online_clients,
        online_non_clients=online_non_clients,
        active_generations=len(active_generations),
        active_generation_users=len(active_generation_users),
        active_generation_clients=active_clients,
        active_generation_non_clients=active_non_clients,
        active_generations_by_type=active_by_type,
        active_generations_by_provider=active_by_provider,
        test_payments_count=test_payments_count,
        test_payments_total=test_payments_total,
        real_payments_count=real_payments_count,
        real_payments_total=real_payments_total,
        api_costs_today=api_costs_today,
        last_requests=last_requests,
        segments=segments,
    )


def render_stats_message(stats: AdminStats) -> str:
    type_labels = {
        "animate_photo": "Оживление фото",
    }
    type_provider = {
        "animate_photo": "KlingAI",
    }
    provider_labels = {
        "klingai": "KlingAI",
    }
    segments_order = [
        ("lead", "🆕 Лиды"),
        ("qual", "✨ Квалы"),
        ("client", "💎 Клиенты"),
    ]
    provider_parts = []
    for key, count in stats.active_generations_by_provider.items():
        label = provider_labels.get(key, key)
        provider_parts.append(f"{label}: {_fmt_int(count)}")
    api_load_suffix = f" ({', '.join(provider_parts)})" if provider_parts else ""
    lines = [
        "📊 Статистика бота",
        "",
        f"👥 Всего пользователей: {_fmt_int(stats.total_users)}",
        f"🔥 Активных сегодня: {_fmt_int(stats.active_today)}",
        f"🎨 Всего генераций: {_fmt_int(stats.generations_total)}",
        f"🎮 Генераций сегодня: {_fmt_int(stats.generations_today)}",
        f"⌨️ Потрачено симв. сегодня: {_fmt_int(stats.spent_today)}",
        f"💰 Всего платежей: {_fmt_money(stats.payments_total)} ₽",
        f"💳 Платежей сегодня: {_fmt_money(stats.payments_today)} ₽",
        f"🧪 Тестовые платежи: {_fmt_int(stats.test_payments_count)} ({_fmt_money(stats.test_payments_total)} ₽)",
        f"✅ Боевые платежи: {_fmt_int(stats.real_payments_count)} ({_fmt_money(stats.real_payments_total)} ₽)",
        "",
        f"🟢 Онлайн сейчас (1 мин): {_fmt_int(stats.online_now)}",
        f"💎 Клиенты онлайн: {_fmt_int(stats.online_clients)}",
        f"👥 Остальные онлайн: {_fmt_int(stats.online_non_clients)}",
        f"⚙️ Нагрузка на API (генерации): {_fmt_int(stats.active_generations)}{api_load_suffix}",
        (
            "👥 Генерируют сейчас: "
            f"{_fmt_int(stats.active_generation_users)} "
            f"(клиенты {_fmt_int(stats.active_generation_clients)} / "
            f"не клиенты {_fmt_int(stats.active_generation_non_clients)})"
        ),
        "🎬 В работе сейчас:",
    ]

    if stats.active_generations_by_type:
        ordered = []
        for key in type_labels:
            if key in stats.active_generations_by_type:
                ordered.append(key)
        for key in stats.active_generations_by_type:
            if key not in ordered:
                ordered.append(key)
        for key in ordered:
            count = stats.active_generations_by_type.get(key, 0)
            if count <= 0:
                continue
            label = type_labels.get(key, key)
            provider = type_provider.get(key)
            if provider:
                label = f"{label} ({provider})"
            lines.append(f"• {label}: {_fmt_int(count)}")
    else:
        lines.append("• Нет активных генераций")

    lines.append("")
    lines.append("💸 Расходы на API сегодня:")
    for provider_key in ("klingai",):
        count, rub, usd = stats.api_costs_today.get(provider_key, (0, Decimal("0"), Decimal("0")))
        label = provider_labels.get(provider_key, provider_key)
        lines.append(f"• {label}: {_fmt_int(count)} ген | {_fmt_money(rub)} ₽ / {_fmt_usd(usd)} $")

    lines.append("")
    lines.append("🧾 Последние 10 запросов:")
    if stats.last_requests:
        for item in stats.last_requests:
            ts = item.timestamp
            time_label = ts.strftime("%H:%M")
            seg = item.segment or "-"
            gtype = item.generation_type or "unknown"
            status = item.status or "unknown"
            label = type_labels.get(gtype, gtype)
            provider = type_provider.get(gtype)
            if provider:
                label = f"{label} ({provider})"
            lines.append(f"• {time_label} | {item.user_id} ({seg}) | {label} | {status}")
    else:
        lines.append("• Нет данных")

    lines.append("")
    lines.append("📈 Сегменты пользователей:")

    def _segment_line(seg_key: str, label: str) -> str:
        cnt, pct = stats.segments.get(seg_key, (0, 0.0))
        return f"{label}: {_fmt_int(cnt)} ({pct:.1f}%)"

    for key, label in segments_order:
        lines.append(_segment_line(key, label))
    return "\n".join(lines)
