# SPDX-License-Identifier: GPL-3.0-or-later
"""Manual audio resource health check entry point."""

from core.audio.audio_resource_health import (
    collect_audio_resource_health,
    format_audio_resource_health,
)


def main():
    report = collect_audio_resource_health()
    print(format_audio_resource_health(report))
    return 0 if report.get("summary", {}).get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())

