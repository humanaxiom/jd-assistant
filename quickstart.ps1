<#
.SYNOPSIS
    Deprecated alias for `launch.ps1`. Forwards everything and warns once.

.DESCRIPTION
    The scripts are now a trio with one job each — `build.ps1`, `launch.ps1`,
    `teardown.ps1` — so "quickstart" no longer says which of the three it is.

    This shim exists because the old name is in older notes, in shell history and in
    people's fingers, and a rename that answers with "command not found" teaches nothing.
    It forwards every argument to `launch.ps1` unchanged.

    ⚠ `-Down` is gone: teardown is `.\teardown.ps1`, which can also drop the volumes and
    clear the one-shot containers compose leaves behind. Passing `-Down` here fails with
    that instruction rather than silently starting the stack you meant to stop.
#>
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments)][string[]]$Forwarded)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Forwarded -contains '-Down') {
    Write-Host ''
    Write-Host '  quickstart.ps1 -Down has been replaced.' -ForegroundColor Yellow
    Write-Host '    .\teardown.ps1                 stop, keep the data' -ForegroundColor Yellow
    Write-Host '    .\teardown.ps1 -Volumes        ...and discard the Bank' -ForegroundColor Yellow
    Write-Host '    .\teardown.ps1 -Orphans        ...and clear stale one-shot containers' -ForegroundColor Yellow
    Write-Host ''
    exit 1
}

Write-Host '  quickstart.ps1 is now .\launch.ps1 (build.ps1 / launch.ps1 / teardown.ps1).' -ForegroundColor Yellow
Write-Host '  Forwarding...' -ForegroundColor Yellow

& (Join-Path $PSScriptRoot 'launch.ps1') @Forwarded
exit $LASTEXITCODE
