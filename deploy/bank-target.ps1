<#
.SYNOPSIS
    Print which JD Bank this checkout's `docker compose` will act on — and, with
    -Guard, refuse if it may not.

.DESCRIPTION
    The `make` face of deploy\BankTarget.ps1. Makefile targets run plain `docker
    compose`, which follows `COMPOSE_PROJECT_NAME` / `JD_IMAGE_TAG` from the environment
    and then the checkout's `.env` — so in a second checkout they already act on that
    checkout's Bank. This makes that visible, and for the targets that (re)create the
    long-running services (`make up`, `make down`, `make migrate`) it applies the same
    guard the scripts do: no recreating the LIVE api/worker from another checkout's code.

.PARAMETER Guard
    Apply the guard; exit 1 on a refusal.

.PARAMETER Destructive
    Guard as a destructive action (see Test-BankAction).

.PARAMETER Builds
    Guard as an action that builds the app images.

.EXAMPLE
    pwsh -NoProfile -File deploy/bank-target.ps1
    pwsh -NoProfile -File deploy/bank-target.ps1 -Guard
#>
[CmdletBinding()]
param([switch]$Guard, [switch]$Destructive, [switch]$Builds)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
. (Join-Path $PSScriptRoot 'BankTarget.ps1')

$target = Resolve-BankTarget -Root $root
Write-BankTarget -Target $target
if ($Guard) {
    try {
        Assert-ComposeAgrees -Target $target
        Assert-BankAction -Target $target -Destructive:$Destructive -Builds:$Builds
    }
    catch {
        if ("$_" -notlike 'Refused by the bank-target guard*') { Write-Host "  $_" -ForegroundColor Red }
        exit 1
    }
}
Write-Host ''
exit 0
