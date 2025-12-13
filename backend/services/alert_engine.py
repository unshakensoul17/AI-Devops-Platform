from collections import Counter

CRASH_KEYWORDS = ["crash", "fatal", "panic", "oom", "killed"]
SLOW_KEYWORDS = ["timeout", "slow", "latency"]

def detect_alerts(logs: list):
    alerts = []

    # Count levels & services
    levels = Counter(log["level"] for log in logs)
    services = Counter(log["service"] for log in logs)

    # ERROR spike
    if levels.get("ERROR", 0) >= 5:
        alerts.append("❗ *ERROR spike detected* (>5 errors)")

    # Service failure
    for svc, count in services.items():
        if count >= 3:
            alerts.append(f"🔥 *Service failure*: `{svc}` ({count} errors)")

    # Crash detection
    for log in logs:
        if any(k in log["message"].lower() for k in CRASH_KEYWORDS):
            alerts.append(f"💥 *Crash detected*\n`{log['message'][:200]}`")
            break

    # Slow / timeout
    for log in logs:
        if any(k in log["message"].lower() for k in SLOW_KEYWORDS):
            alerts.append(f"🐢 *Slow response*\n`{log['message'][:200]}`")
            break

    return alerts
