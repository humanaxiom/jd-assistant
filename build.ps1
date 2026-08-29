<#
.SYNOPSIS
    Build the JD Bank images, and prove they are the ones that would ship.

.DESCRIPTION
    The first of the three scripts — build → launch → teardown.

    `launch.ps1` builds as a side effect of starting, and `deploy\bundle.ps1` builds as
    a side effect of packaging. Neither answers the question this one exists for: **is
    the image I would ship current with the source, and is it portable?** That question
    had no home, which is how the compose PROJECT NAME ended up baked into the image
    names and a bundle that could not install under any other project.

    WHAT IT DOES
      1. builds every compose image (`-NoCache` after a dependency change);
      2. runs `deploy\deploy-check.sh` — the same invariants CI enforces as
         "Gate: deployable offline", above all that image names do NOT depend on the
         compose project name;
      3. reports each image's id and age, so a stale one is visible rather than assumed;
      4. with `-Bundle`, cuts the offline deploy bundle as well.

    IT DOES NOT START ANYTHING. Building and running are separate on purpose: a build
    that also launches cannot be used to check a change before you run it.

.PARAMETER NoCache
    Rebuild without the layer cache. Use after changing `core/requirements*.txt` or the
    Dockerfile. A plain build reuses layers and will NOT notice a moved dependency.

.PARAMETER Bundle
    Also cut the offline deploy bundle (`deploy\bundle.ps1` -> .\dist). Needs the stack
    RUNNING, because the bundle carries a Postgres and a Neo4j dump.

.PARAMETER SkipCheck
    Skip the deployability check. Only for iterating on a broken tree.

.EXAMPLE
    .\build.ps1
    Build and verify.

.EXAMPLE
    .\build.ps1 -NoCache
    After a dependency or Dockerfile change.

.EXAMPLE
    .\build.ps1 -Bundle
    Build, verify, and cut the offline bundle (stack must be up).
#>
[CmdletBinding()]
param(
    [switch]$NoCache,
    [switch]$Bundle,
    [switch]$SkipCheck
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

function Write-Step { param([string]$T) Write-Host "`n=== $T ===" -ForegroundColor Cyan }
function Write-Ok { param([string]$T) Write-Host "  [ok]   $T" -ForegroundColor Green }
function Write-Warn { param([string]$T) Write-Host "  [warn] $T" -ForegroundColor Yellow }
function Write-Info { param([string]$T) Write-Host "  $T" }

function Resolve-Bash {
    <#  A bash that can see THIS docker — which is not necessarily the first on PATH.

        🔴 On Windows, `bash` usually resolves to C:\windows\system32\bash.exe, which is
        WSL. WSL has its own PATH and its own (or no) docker, so
        `deploy\deploy-check.sh` run through it reports "the compose file does not
        resolve" — a confident failure about a repo that is perfectly fine. Measured on
        this box while writing this script.

        Git Bash shares the Windows docker, so prefer it and treat a system32 bash as a
        last resort. Returns $null when nothing usable is found, so the caller can say
        so plainly rather than throw a lie about the compose file. #>
    $candidates = @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    $onPath = (Get-Command bash -ErrorAction SilentlyContinue).Source
    if ($onPath -and $onPath -notlike "$env:WINDIR*") { return $onPath }
    return $null
}

function Invoke-Checked {
    <#  $LASTEXITCODE is the only honest signal: a native command's failure does not trip
        ErrorActionPreference, so without this a failed build scrolls past and the script
        reports success over a stale image. #>
    param([string]$What, [scriptblock]$Body)
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

Write-Step 'Preflight'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker not found on PATH. This project has no host-Python fallback (ADR-006).'
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is installed but not running.' }
Write-Ok 'Docker daemon is up'
if (-not (Test-Path 'docker-compose.yml')) { throw "No docker-compose.yml in $PSScriptRoot" }

# Asked of compose, never hardcoded — a service added to docker-compose.yml is built and
# checked here without anyone remembering to edit this script.
$images = @(& docker compose config --images 2>$null | Sort-Object -Unique | Where-Object { $_ })
if (-not $images) { throw 'Could not read the image list from docker compose.' }
Write-Info "Images this project needs: $($images -join ', ')"

# ── Build ───────────────────────────────────────────────────────────────────
Write-Step 'Building'
if ($NoCache) {
    Write-Info 'Rebuilding without the layer cache (dependency or Dockerfile change)...'
    Invoke-Checked 'docker compose build --no-cache' { & docker compose build --no-cache }
}
else {
    # Quiet: a fully-cached build has nothing to say and its layer chatter buries the
    # report below. Failures still print — quiet suppresses progress, not errors.
    Invoke-Checked 'docker compose build' { & docker compose --progress quiet build }
}
Write-Ok 'Images built'

# ── Deployability ───────────────────────────────────────────────────────────
if (-not $SkipCheck) {
    Write-Step 'Checking this build is deployable (Directive #1)'
    $bash = Resolve-Bash
    if (-not $bash) {
        Write-Warn 'No usable bash found, so the deployability check did NOT run.'
        Write-Info '  It is one script — deploy/deploy-check.sh — and CI runs it on every'
        Write-Info '  push as "Gate: deployable offline". Run `make deploy-check` in a'
        Write-Info '  Git Bash shell to get the same answer here.'
    }
    else {
        & $bash 'deploy/deploy-check.sh'
        if ($LASTEXITCODE -ne 0) {
            throw 'deploy-check FAILED — this build would not install on a fresh box. See above.'
        }
    }
}
else { Write-Warn 'Deployability check skipped (-SkipCheck)' }

# ── What did we actually build? ─────────────────────────────────────────────
# A build that says "ok" while reusing a week-old layer is the failure mode here, so the
# ages are printed rather than trusted.
Write-Step 'Images'
foreach ($img in $images) {
    $info = & docker image inspect $img --format '{{.Id}} {{.Created}}' 2>$null
    if (-not $info) { Write-Warn ("{0,-24} NOT PRESENT" -f $img); continue }
    $parts = "$info".Trim().Split(' ')
    $id = $parts[0] -replace '^sha256:', ''
    $age = ''
    try {
        $created = [datetime]::Parse($parts[1])
        $span = (Get-Date).ToUniversalTime() - $created.ToUniversalTime()
        $age = if ($span.TotalHours -lt 1) { "{0:N0}m ago" -f $span.TotalMinutes }
        elseif ($span.TotalDays -lt 1) { "{0:N0}h ago" -f $span.TotalHours }
        else { "{0:N0}d ago" -f $span.TotalDays }
    }
    catch { $age = 'age unknown' }
    Write-Info ("  {0,-24} {1}  built {2}" -f $img, $id.Substring(0, 12), $age)
}

# ── Bundle ──────────────────────────────────────────────────────────────────
if ($Bundle) {
    Write-Step 'Cutting the offline deploy bundle'
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'deploy\bundle.ps1')
    if ($LASTEXITCODE -ne 0) { throw "bundle.ps1 failed (exit $LASTEXITCODE)" }
}

Write-Host "`n  Next:" -ForegroundColor Cyan
Write-Info '  .\launch.ps1                                 start the stack'
Write-Info '  make gates                                   full CI-identical suite'
if (-not $Bundle) {
    Write-Info '  .\build.ps1 -Bundle                          ...and cut the offline bundle'
}
Write-Host ''
