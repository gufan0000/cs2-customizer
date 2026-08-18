# RN-092: CI reads the audit's own verdict line, NOT the process exit code.
#
# Why (see scripts/_audit_verdict.py for the full story):
#   Qt/keyboard/audio teardown rewrites the exit code in BOTH directions.
#   2026-08-17 run 41217bf: tab_order_audit printed "RESULT rc=0" and the
#   process still exited 1 with no traceback  -> false RED.
#   The reverse (non-zero washed to 0) is already on the QA ledger -> false GREEN.
#
# This gate cannot be washed green: a missing verdict line is a failure.
#
# NOTE: messages are ASCII on purpose. This file is executed by pwsh on the
# runner and by Windows PowerShell 5.1 locally; a BOM-less UTF-8 file is read
# as ANSI by 5.1 and non-ASCII text would be mangled in the CI log.
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$LogPath
)

if (-not (Test-Path $LogPath)) {
    Write-Host "::error::[$Name] no audit log at $LogPath - the audit never ran"
    exit 1
}

$m = Select-String -Path $LogPath -Pattern "^RESULT\s+$Name\s+rc=(-?\d+)\s*$" |
     Select-Object -Last 1

if (-not $m) {
    Write-Host "::error::[$Name] no 'RESULT $Name rc=<n>' line in the log - the audit died before delivering a verdict, treating as FAILURE"
    exit 1
}

$rc = [int]$m.Matches[0].Groups[1].Value
if ($rc -ne 0) {
    Write-Host "::error::[$Name] audit verdict is FAIL (RESULT $Name rc=$rc)"
    exit 1
}

Write-Host "[$Name] audit verdict: RESULT rc=0"
exit 0
