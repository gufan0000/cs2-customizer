# SPDX-License-Identifier: GPL-3.0-or-later
"""Freshness only gates immediate effects, never state transitions."""
import time

from core.gun_sound_profiles import STALE_PACKET_SECONDS


def packet_is_stale(data):
    try:
        received = data.get("_cs2customizer_recv_monotonic")
        return received is not None and time.monotonic() - float(received) > STALE_PACKET_SECONDS
    except (AttributeError, TypeError, ValueError):
        return False
