<#
.SYNOPSIS
    End-to-end: a second checkout with NO `.env` cannot run a producer against the live
    Bank through `make`.

.DESCRIPTION
    Creates a throwaway linked git worktree (no `.env`), copies THIS tree's Makefile and
    deploy kit into it (so the check covers uncommitted edits too), and asserts:
      1. `make -n ingest` / `make -n embed-roles` show the bank-target guard BEFORE the
         `docker compose run` line;
      2. the guard, run there, REFUSES — the project resolves to `jd-bank` (the live
         name) from a linked worktree, and on a box running the live stack its
         containers belong to another checkout.
    Nothing is executed against any Bank: `make -n` only prints, and the guard is
    read-only (`docker ps` / `docker compose config`). Removes the worktree afterwards.

    Needs git, make, pwsh and docker. Run by deploy/deploy-check.sh.

        pwsh -NoProfile -File deploy/tests/make-guard.tests.ps1
#>
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$scratch = Join-Path ([IO.Path]::GetTempPath()) ("make-guard-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$failures = 0
$passed = 0
function Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = '')
    if ($Ok) { $script:passed++; Write-Host "  [ok]   $Name" }
    else { $script:failures++; Write-Host "  [FAIL] $Name  $Detail" -ForegroundColor Red }
}

& git -C $repo worktree add --detach $scratch HEAD *> $null
if ($LASTEXITCODE -ne 0) { Write-Host '  [FAIL] could not create a scratch worktree' -ForegroundColor Red; exit 1 }
try {
    # The tree under test, not HEAD: copy the Makefile and the deploy kit over.
    Copy-Item -LiteralPath (Join-Path $repo 'Makefile') -Destination $scratch -Force
    Copy-Item -LiteralPath (Join-Path $repo 'docker-compose.yml') -Destination $scratch -Force
    Copy-Item -Path (Join-Path $repo 'deploy/*.ps1') -Destination (Join-Path $scratch 'deploy') -Force
    if (Test-Path -LiteralPath (Join-Path $scratch '.env')) { throw 'scratch worktree unexpectedly has a .env' }

    Write-Host "`n=== make -n in a second checkout with no .env ==="
    foreach ($target in @('ingest', 'embed-roles')) {
        $out = @(& make -C $scratch -n $target 2>&1 | ForEach-Object { "$_" })
        $g = -1; $c = -1
        for ($i = 0; $i -lt $out.Count; $i++) {
            if ($g -lt 0 -and $out[$i] -match 'bank-target\.ps1 -Guard') { $g = $i }
            if ($c -lt 0 -and $out[$i] -match 'docker compose run') { $c = $i }
        }
        Check "make -n ${target}: guard line precedes the compose call" ($g -ge 0 -and $c -gt $g) ("`n" + ($out -join "`n"))
    }

    Write-Host "`n=== The guard, run in that checkout ==="
    Push-Location $scratch
    try {
        $guardOut = @(& pwsh -NoProfile -File (Join-Path $scratch 'deploy/bank-target.ps1') -Guard 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    }
    finally { Pop-Location }
    $text = $guardOut -join "`n"
    Check 'resolves to the LIVE project name jd-bank' ($text -match 'project\s+jd-bank\s') $text
    Check 'REFUSES it (exit 1)' ($code -eq 1 -and $text -match 'REFUSED') "exit=$code`n$text"
}
finally {
    & git -C $repo worktree remove --force $scratch *> $null
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host ''
if ($failures) { Write-Host "  MAKE-GUARD TESTS: $failures FAILED, $passed passed" -ForegroundColor Red; exit 1 }
Write-Host "  MAKE-GUARD TESTS: all $passed passed" -ForegroundColor Green
exit 0
