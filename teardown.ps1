<#
.SYNOPSIS
    Stop the JD Bank stack — and, only if you say so, discard its data.

.DESCRIPTION
    The counterpart to `launch.ps1`. By default it stops and removes the CONTAINERS and
    keeps every named volume, so the parsed archive, the roles and the vector store all
    survive. Discarding data is never the default and never implicit.

    IT ALSO CLEANS UP WHAT COMPOSE WILL NOT. One-shot `docker run` jobs (the canonical
    producer, ad-hoc probes) are not compose services, so `docker compose down` leaves
    them behind forever. Three of them sat "Exited" for a week on this box, making every
    compose command print an orphan warning that everyone learned to ignore — which is
    how a real warning gets missed. `-Orphans` removes them.

.PARAMETER Volumes
    ALSO delete the named volumes: `pgdata` (the whole relational Bank) and `neo4jdata`
    (every vector). DESTRUCTIVE and irreversible without a bundle. You are shown exactly
    what will be lost and asked to confirm, unless -Force.

.PARAMETER Orphans
    Remove EXITED one-shot containers belonging to this project that compose does not
    manage — the `jd-canonical-*` producer runs and similar. Running containers are never
    touched.

.PARAMETER ProjectName
    Which compose project to tear down. Default `jd-bank`. Use `jd-bank-test` to remove
    the isolated stack that `deploy\install.ps1 -Isolated` creates.

.PARAMETER Bundle
    ALSO delete the offline deploy bundle in .\dist. It is a build artifact — `make
    bundle` recreates it — but it is ~1.4 GB, so removing it is explicit.

.PARAMETER Force
    Skip the confirmation prompt for -Volumes. For scripts; think before you type it.

.EXAMPLE
    .\teardown.ps1
    Stop the stack. Data kept.

.EXAMPLE
    .\teardown.ps1 -Orphans
    Stop the stack and clear the stale one-shot containers compose leaves behind.

.EXAMPLE
    .\teardown.ps1 -ProjectName jd-bank-test -Volumes -Force
    Remove the isolated test stack completely — the normal way to clean up after
    rehearsing a deploy.

.EXAMPLE
    .\teardown.ps1 -Volumes
    Stop the stack AND discard the Bank. Asks first.
#>
[CmdletBinding()]
param(
    [switch]$Volumes,
    [switch]$Orphans,
    [string]$ProjectName = 'jd-bank',
    [switch]$Bundle,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

function Write-Step { param([string]$T) Write-Host "`n=== $T ===" -ForegroundColor Cyan }
function Write-Ok { param([string]$T) Write-Host "  [ok]   $T" -ForegroundColor Green }
function Write-Warn { param([string]$T) Write-Host "  [warn] $T" -ForegroundColor Yellow }
function Write-Info { param([string]$T) Write-Host "  $T" }

$Compose = @('--project-name', $ProjectName)

Write-Step 'Preflight'
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running.' }
Write-Ok "Docker daemon is up (project: $ProjectName)"

# ── What is about to be lost? ───────────────────────────────────────────────
# Shown BEFORE anything is removed. A destructive command that reports what it did is
# not the same as one that says what it is about to do.
if ($Volumes) {
    Write-Step 'What -Volumes will DESTROY'
    $vols = @(& docker volume ls --format '{{.Name}}' |
        Where-Object { $_ -like "${ProjectName}_*" })
    if (-not $vols) { Write-Info '  (no named volumes for this project)' }
    foreach ($v in $vols) {
        $size = (& docker system df -v --format '{{range .Volumes}}{{.Name}} {{.Size}}
{{end}}' 2>$null | Where-Object { $_ -like "$v *" }) -replace "^$v ", ''
        Write-Warn ("{0,-32} {1}" -f $v, $(if ($size) { "$size".Trim() } else { 'size unknown' }))
    }
    Write-Info ''
    Write-Info '  This is the parsed archive, every harmonized role, the review history'
    Write-Info '  and the vector store. `make ingest` + `make embed` rebuild it from the'
    Write-Info '  archive; a `make bundle` artifact restores it directly.'

    if (-not $Force) {
        $answer = Read-Host "`n  Type the project name ($ProjectName) to confirm deletion"
        if ($answer -ne $ProjectName) {
            Write-Info "`n  Not confirmed — nothing was deleted."
            return
        }
    }
}

# ── Stop ────────────────────────────────────────────────────────────────────
Write-Step 'Stopping the stack'
$downArgs = @('down', '--remove-orphans')
if ($Volumes) { $downArgs += '--volumes' }
& docker compose @Compose @downArgs
if ($LASTEXITCODE -ne 0) { throw "docker compose down failed (exit $LASTEXITCODE)" }

if ($Volumes) { Write-Ok 'Stack and volumes removed — the Bank is gone.' }
else { Write-Ok 'Stopped. Named volumes were KEPT — the Bank is intact.' }

# ── One-shot leftovers compose does not manage ──────────────────────────────
if ($Orphans) {
    Write-Step 'Clearing stale one-shot containers'
    # EXITED only, and matched by name prefix. A running container is never touched:
    # a long producer run must not be killed by a teardown of the app stack.
    $stale = @(& docker ps -a --filter 'status=exited' --format '{{.Names}}' |
        Where-Object { $_ -like 'jd-canonical-*' -or $_ -like "$ProjectName-*-run-*" })
    if (-not $stale) { Write-Ok 'None found' }
    foreach ($c in $stale) {
        & docker rm $c *> $null
        if ($LASTEXITCODE -eq 0) { Write-Ok "removed $c" } else { Write-Warn "could not remove $c" }
    }
}

# ── The offline bundle ──────────────────────────────────────────────────────
if ($Bundle) {
    Write-Step 'Removing the offline deploy bundle'
    $dist = Join-Path $PSScriptRoot 'dist'
    if (Test-Path -LiteralPath $dist) {
        $mb = [math]::Round((Get-ChildItem -LiteralPath $dist -Recurse -File |
                    Measure-Object -Property Length -Sum).Sum / 1MB)
        Remove-Item -LiteralPath $dist -Recurse -Force
        Write-Ok "removed .\dist ($mb MB) — `make bundle` recreates it"
    }
    else { Write-Ok '.\dist is already absent' }
}

# ── What is left ────────────────────────────────────────────────────────────
Write-Step 'Remaining'
$left = @(& docker ps -a --format '{{.Names}}' | Where-Object { $_ -like "$ProjectName*" })
if ($left) { foreach ($c in $left) { Write-Info "  $c" } }
else { Write-Ok "no $ProjectName containers remain" }

Write-Host "`n  Next:" -ForegroundColor Cyan
Write-Info '  .\launch.ps1                                 bring it back up'
if ($Volumes) {
    Write-Info '  .\deploy\install.ps1 -BundleDir <bundle>     ...or restore from a bundle'
    Write-Info '  make ingest JD_ARCHIVE_PATH=<archive>        ...or re-parse from scratch'
}
Write-Host ''
