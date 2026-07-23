"""Small formatting helpers reused across every UI tab."""
from __future__ import annotations

import time


def human_bytes(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} EB"


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def time_ago(epoch_seconds: float) -> str:
    return human_duration(time.time() - epoch_seconds) + " ago"
