# Offline reliability and performance improvements (2026-10-25)

This batch preserves the application's audio, icon, theme and page features. Real game/device acceptance is a separate step; offline regression coverage does not claim it.

- Configuration snapshots flush current state and share the save lock through restore/reload. A failed reload rolls back disk and memory; indexed paths cannot restore or prune files outside the snapshot directory. Unknown future configuration fields survive a save; malformed scalar types and nonfinite window coordinates fall back safely.
- Theme subscriptions no longer retain destroyed page objects, including deletion through Qt parents. Notification iteration tolerates unsubscription. Audio maintenance has a bounded queue, merges pending refreshes of the same kind and cancels pending stages on shutdown. Shutdown waits before releasing the audio manager; timed-out work cannot race manager cleanup. Icon cleanup invalidates in-flight decoding.
- GSI accepts JSON objects with a 1 MiB input limit. Logs redact exception chains and stack text as well as the message. Setuptools is pinned to 84.1.0 to address [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w), affecting the legacy Windows wheel installation path.
- Resource enumeration uses scandir and normalizes extensions once per scan. A health collection checks each shared complete kill style once. Sound pages assign parents during construction, avoiding repeated subtree attachment while retaining full styles, controls and category tabs.
- Performance tools require successful child exit and complete sample/page sets. Pages are actually destroyed between iterations. Temporary-profile and sandbox cleanup verify directory boundaries. Runtime state is isolated in tests. The real-game test runner starts each app-dependent case from its own seed and verifies readback, preventing conflicting opacity/style seeds from contaminating one another.

## Measurements

On one Windows host, with three warmups and twelve alternating before/after samples, scanning 10,000 empty audio filenames fell from **166.38 ms to 4.53 ms**, with equal results and sorting. This measures directory scanning, not decoding or overall application speed.

With full QSS and five measured construction runs per page, explicit widget parenting reduced constructor medians:

| Page | Before | After |
|---|---:|---:|
| Kill sound | 281.54 ms | 155.60 ms |
| Kill voice | 265.27 ms | 181.57 ms |
| Switch weapon | 265.91 ms | 160.17 ms |
| Reload sound | 221.72 ms | 124.29 ms |

All measured widgets were destroyed and theme subscription counts returned to baseline. Timing is host-specific; layout/behavior regressions remain independent acceptance gates.

## Validation scope

New regression tests cover invalid config values, future-field round trips, concurrent snapshot restore/save, outside snapshot paths, reload rollback, benchmark failures, Qt parent destruction, refresh coalescing and stop, exception redaction, GSI size/type bounds and shared-resource deduplication. Existing configuration, audio, lifecycle and sound-page tests are also exercised. Complete public CI is required for delivery; no private CI or real-device run is part of this batch.
