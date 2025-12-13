from datetime import datetime, timedelta
from collections import Counter

# in-memory alert cooldown (FREE tier safe)
ALERT_COOLDOWN = {}
COOLDOWN_MINUTES = 5

def detect_alerts(logs: list[dict]) -> list[str]:
    alerts = []

    if not logs:
        return alerts

    now = datetime.utcnow()

    # -----------------------------
    # 1. ERROR SPIKE DETECTION
    # -----------------------------
    error_logs = [l for l in logs if l["level"] == "ERROR"]

    if len(error_logs) >= 5:
        key = "ERROR_SPIKE"

        if not _in_cooldown(key, now):
            ALERT_COOLDOWN[key] = now
            alerts.append(
                "🔥 *CRITICAL*\n"
                f"Error spike detected: {len(error_logs)} errors in short time window"
            )

    # -----------------------------
    # 2. SERVICE FAILURE GROUPING
    # -----------------------------
    service_counts = Counter(l["service"] for l in error_logs)

    for service, count in service_counts.items():
        if count >= 3:
            key = f"SERVICE_FAIL_{service}"

            if not _in_cooldown(key, now):
                ALERT_COOLDOWN[key] = now
                alerts.append(
                    "🚨 *HIGH*\n"
                    f"Service failure detected\n"
                    f"Service: `{service}`\n"
                    f"Errors: {count}"
                )

    # -----------------------------
    # 3. SAME ERROR REPEATING
    # -----------------------------
    msg_counts = Counter(l["message"] for l in error_logs)

    for msg, count in msg_counts.items():
        if count >= 3:
            key = f"RECURRING_{hash(msg)}"

            if not _in_cooldown(key, now):
                ALERT_COOLDOWN[key] = now
                alerts.append(
                    "⚠️ *WARNING*\n"
                    f"Recurring error detected ({count} times)\n"
                    f"`{msg[:120]}`"
                )

    return alerts


def _in_cooldown(key: str, now: datetime) -> bool:
    if key not in ALERT_COOLDOWN:
        return False

    return now - ALERT_COOLDOWN[key] < timedelta(minutes=COOLDOWN_MINUTES)
