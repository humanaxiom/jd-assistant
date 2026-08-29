<#
.SYNOPSIS
    Install the JD Bank on a fresh box from an offline bundle. No internet required.

.DESCRIPTION
    Takes the directory `bundle.ps1` produced and brings up a working stack: loads the
    images, restores the Postgres Bank and the Neo4j vector store, starts the app, and
    VERIFIES what it installed against the bundle's manifest.

    IT NEVER REACHES THE NETWORK. Every compose call passes `--no-build --pull never`,
    so a missing image FAILS LOUDLY instead of silently reaching for Docker Hub. That is
    the whole point: an install that quietly pulls has not proved anything about the
    offline box you actually care about.

    THE RESTORE TRAP THIS SCRIPT REFUSES TO WALK INTO
    `pg_restore --data-only` into an already-migrated database silently destroys the
    Bank and exits 0 — measured on a real dump, recorded in docs/archive/. So this
    script restores a FULL custom-format dump into an EMPTY database, and REFUSES to run
    if the target database already has tables. Use -Force only if you mean to discard
    what is there.

    WHAT IT DOES NOT DO
    Ingest. Migrate from scratch. Embed. The bundle already carries a parsed, clustered,
    embedded Bank — running `make ingest` here would be re-doing work you shipped.

.PARAMETER BundleDir
    The bundle directory (contains images.tar, postgres.dump, neo4j.dump, MANIFEST.txt).

.PARAMETER ProjectName
    Compose project name. Default `jd-bank`. Override to REHEARSE an install beside a
    live stack — a different name means different volumes and containers, so nothing
    existing is touched. Combine with the JD_*_PORT variables to avoid port collisions.

.PARAMETER SkipImages
    Do not `docker load`. For a re-run on a box whose images are already loaded.

.PARAMETER Force
    Allow restoring over a database that already has tables. DESTRUCTIVE.

.PARAMETER NoCas
    Start the API with CAS SSO off, so the UI is reachable without an SFU login.

.EXAMPLE
    .\deploy\install.ps1 -BundleDir .\dist\jd-bank-bundle
    The normal fresh-box install.

.EXAMPLE
    .\deploy\install.ps1 -BundleDir .\dist\jd-bank-bundle -ProjectName jd-bank-verify
    Rehearse the whole install beside the live stack, touching none of its data.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [string]$ProjectName = 'jd-bank',
    [switch]$SkipImages,
    [switch]$Force,
    [switch]$NoCas
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')

function Write-Step { param([string]$T) Write-Host "`n=== $T ===" -ForegroundColor Cyan }
function Write-Ok { param([string]$T) Write-Host "  [ok]   $T" -ForegroundColor Green }
function Write-Warn { param([string]$T) Write-Host "  [warn] $T" -ForegroundColor Yellow }
function Write-Info { param([string]$T) Write-Host "  $T" }
function Write-Fail { param([string]$T) Write-Host "  [FAIL] $T" -ForegroundColor Red }

function Invoke-Checked {
    param([string]$What, [scriptblock]$Body)
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

# Every compose call in this script goes through here, so the offline flags cannot be
# forgotten on one of them. `--pull never` + `--no-build` is what makes "offline" a
# property of the run rather than a hope about the network.
$ComposeBase = @('--project-name', $ProjectName)
function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments)][string[]]$ComposeArgs)
    & docker compose @ComposeBase @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($ComposeArgs -join ' ') failed (exit $LASTEXITCODE)" }
}

$ApiPort = if ($env:JD_API_PORT) { $env:JD_API_PORT } else { '25800' }

# ── Preflight ───────────────────────────────────────────────────────────────
Write-Step 'Preflight'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker not found on PATH. Install Docker Desktop — this project has no host-Python fallback (ADR-006).'
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is installed but not running. Start Docker Desktop and re-run.' }
Write-Ok 'Docker daemon is up'

if (-not (Test-Path 'docker-compose.yml')) {
    throw "No docker-compose.yml beside $PSScriptRoot — copy the whole repo to this box, not just deploy/."
}
Write-Ok 'Repo present (api/worker bind-mount ./core, so the source must be here)'

$BundleDir = (Resolve-Path -LiteralPath $BundleDir).Path
$imagesTar = Join-Path $BundleDir 'images.tar'
$pgDump = Join-Path $BundleDir 'postgres.dump'
$neoDump = Join-Path $BundleDir 'neo4j.dump'
$manifest = Join-Path $BundleDir 'MANIFEST.txt'

foreach ($required in @($pgDump, $neoDump)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Bundle is incomplete: missing $required" }
}
if (-not $SkipImages -and -not (Test-Path -LiteralPath $imagesTar)) {
    throw "Bundle is incomplete: missing $imagesTar (or pass -SkipImages)"
}
Write-Ok "Bundle looks complete: $BundleDir"
if (Test-Path -LiteralPath $manifest) {
    Write-Info ''
    Get-Content -LiteralPath $manifest | Select-Object -First 6 | ForEach-Object { Write-Info "  | $_" }
    Write-Info ''
}
else { Write-Warn 'No MANIFEST.txt — cannot cross-check what was cut.' }

if ($NoCas) {
    $env:CAS_ENABLED = 'false'
    Write-Ok 'CAS forced OFF for this run (dev-admin mode; .env not modified)'
}

# ── Images ──────────────────────────────────────────────────────────────────
if (-not $SkipImages) {
    Write-Step 'Loading images'
    Write-Info 'Reading images.tar (no network) ...'
    Invoke-Checked 'docker load' { & docker load -i $imagesTar }
    Write-Ok 'Images loaded'
}
else { Write-Info 'Image load skipped (-SkipImages)' }

# Prove every image compose needs is HERE, before starting anything. Without this the
# first `up` is what discovers a missing image, and on a connected box it would paper
# over the gap by pulling — exactly the failure this script exists to make impossible.
Write-Step 'Verifying images are present locally'
$needed = @(& docker compose @ComposeBase config --images 2>$null | Sort-Object -Unique | Where-Object { $_ })
if (-not $needed) { throw 'Could not read the image list from docker compose.' }
$missing = @()
foreach ($img in $needed) {
    & docker image inspect $img *> $null
    if ($LASTEXITCODE -ne 0) { $missing += $img; Write-Fail "missing: $img" }
    else { Write-Ok "present: $img" }
}
if ($missing) {
    throw ("These images are not on this box and this script will NOT pull them: " +
        ($missing -join ', ') + ". Re-cut the bundle with deploy\bundle.ps1.")
}

# ── Data tier ───────────────────────────────────────────────────────────────
Write-Step 'Starting the data tier'
Invoke-Compose up -d --wait --no-build --pull never postgres neo4j redis
Write-Ok 'postgres, neo4j, redis healthy'

# ── Postgres restore ────────────────────────────────────────────────────────
Write-Step 'Restoring Postgres'

$pgId = "$(& docker compose @ComposeBase ps -q postgres)".Trim()
if (-not $pgId) { throw 'postgres container not found after start.' }

# Is the target EMPTY? A count of user tables, not a guess. Restoring a full dump over a
# populated database is how the Bank gets silently destroyed.
$tableCount = & docker compose @ComposeBase exec -T postgres psql -U app -d harness -t -A -c `
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not ask Postgres how many tables it has — refusing to restore blind. Output: $tableCount"
}
$tableCount = [int]("$($tableCount | Select-Object -First 1)".Trim())

if ($tableCount -gt 0 -and -not $Force) {
    throw ("Database 'harness' already has $tableCount tables. This script restores a FULL " +
        "dump into an EMPTY database — restoring over live data is the documented way to " +
        "destroy the Bank. Re-run with -Force to discard what is there, or use a different " +
        "-ProjectName to install beside it.")
}
if ($tableCount -gt 0) {
    Write-Warn "-Force: dropping and recreating 'harness' ($tableCount tables will be lost)"
    Invoke-Checked 'drop database' {
        & docker compose @ComposeBase exec -T postgres psql -U app -d postgres -c `
            "DROP DATABASE IF EXISTS harness WITH (FORCE);"
    }
    Invoke-Checked 'create database' {
        & docker compose @ComposeBase exec -T postgres psql -U app -d postgres -c "CREATE DATABASE harness OWNER app;"
    }
    Write-Ok 'harness recreated empty'
}
else { Write-Ok "Database 'harness' is empty — the only safe target for a full restore" }

Invoke-Checked 'docker cp (postgres dump)' { & docker cp $pgDump "${pgId}:/tmp/jdbank.dump" }
# NOT --data-only. A full custom-format dump into an empty database brings schema, data
# and alembic_version together, so the box lands at head without running a migration.
& docker compose @ComposeBase exec -T postgres pg_restore -U app -d harness --no-owner --no-acl /tmp/jdbank.dump
$restoreExit = $LASTEXITCODE
& docker compose @ComposeBase exec -T postgres rm -f /tmp/jdbank.dump 2>&1 | Out-Null
if ($restoreExit -ne 0) {
    # pg_restore warns about non-fatal things routinely; only a table count can say whether
    # it actually worked, so check rather than trust the exit code either way.
    Write-Warn "pg_restore exited $restoreExit — verifying by row count below rather than trusting it"
}
Write-Ok 'Postgres restore finished'

# ── Neo4j restore ───────────────────────────────────────────────────────────
Write-Step 'Restoring Neo4j'
# `neo4j-admin database load` needs the database STOPPED, so the container comes down and
# a one-off container of the same image loads into the volume.
$neo4jImage = $needed | Where-Object { $_ -like 'neo4j:*' } | Select-Object -First 1
$vol = "${ProjectName}_neo4jdata"

Write-Info 'Stopping neo4j (the load requires the database offline)...'
Invoke-Compose stop neo4j
try {
    Invoke-Checked 'neo4j-admin database load' {
        & docker run --rm -v "${vol}:/data" -v "${BundleDir}:/dumps" $neo4jImage `
            neo4j-admin database load neo4j --from-path=/dumps --overwrite-destination=true
    }
    Write-Ok 'neo4j.dump loaded into the volume'
}
finally {
    Invoke-Compose start neo4j
    Write-Info 'neo4j restarted'
}

# ── App tier ────────────────────────────────────────────────────────────────
Write-Step 'Starting the app'
Invoke-Compose up -d --wait --no-build --pull never
Write-Ok 'All services report healthy'

Write-Step 'Waiting for the API'
$apiUrl = "http://localhost:$ApiPort"
$ready = $false
foreach ($attempt in 1..30) {
    try {
        $resp = Invoke-WebRequest -Uri "$apiUrl/health" -TimeoutSec 3 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    }
    catch { Start-Sleep -Seconds 2 }
}
if ($ready) { Write-Ok "API answering on $apiUrl" }
else { Write-Warn "API did not answer /health within ~60s. Check: docker compose --project-name $ProjectName logs api" }

# ── Verify ──────────────────────────────────────────────────────────────────
# The install is not finished when the containers are up; it is finished when the DATA
# is provably there. A stack that boots against an empty database looks identical to a
# restored one until you ask.
Write-Step 'Verifying the restore'

function Get-Count {
    param([string]$Table)
    $out = & docker compose @ComposeBase exec -T postgres psql -U app -d harness -t -A -c "SELECT count(*) FROM $Table;" 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    return [int]("$($out | Select-Object -First 1)".Trim())
}

$expected = @{}
if (Test-Path -LiteralPath $manifest) {
    foreach ($line in (Get-Content -LiteralPath $manifest)) {
        if ($line -match '^\s{2}(source_documents|parsed_jds|canonical_jds|clusters|dedup_edges)\s+(\d+)\s*$') {
            $expected[$Matches[1]] = [int]$Matches[2]
        }
    }
}

$problems = @()
foreach ($table in @('source_documents', 'parsed_jds', 'canonical_jds', 'clusters', 'dedup_edges')) {
    $actual = Get-Count $table
    if ($null -eq $actual) { Write-Fail ('{0,-18} QUERY FAILED' -f $table); $problems += $table; continue }
    if ($expected.ContainsKey($table)) {
        if ($actual -eq $expected[$table]) { Write-Ok ('{0,-18} {1,8:N0}  (matches the bundle)' -f $table, $actual) }
        else {
            Write-Fail ('{0,-18} {1,8:N0}  EXPECTED {2:N0} from the manifest' -f $table, $actual, $expected[$table])
            $problems += $table
        }
    }
    else {
        Write-Info ('  {0,-18} {1,8:N0}  (no manifest figure to compare)' -f $table, $actual)
        if ($actual -eq 0) { $problems += $table }
    }
}

# Neo4j is the vector store; an empty one means search and the authoring guard are dead
# even though every container is healthy.
$vecOut = & docker compose @ComposeBase exec -T neo4j cypher-shell -u neo4j -p harnesspass --format plain `
    "MATCH (d:JDDocument) RETURN count(d) AS n;" 2>&1
if ($LASTEXITCODE -eq 0) {
    $vecCount = ($vecOut | Select-Object -Last 1)
    Write-Ok "JDDocument vector nodes: $("$vecCount".Trim())"
}
else {
    Write-Fail 'Could not count Neo4j vector nodes'
    $problems += 'neo4j'
}

# ── Result ──────────────────────────────────────────────────────────────────
Write-Step 'Result'
if ($problems) {
    Write-Fail ("Install completed but verification FAILED for: " + ($problems -join ', '))
    Write-Info '  Do not treat this box as deployed. Check the logs above.'
    exit 1
}

Write-Ok 'Installed and verified — the Bank is present, not merely running.'
Write-Host "`n  Open:" -ForegroundColor Cyan
Write-Info "  App          $apiUrl"
Write-Info "  Funnel       $apiUrl/jd-bank/ui/funnel"
Write-Info "  Review queue $apiUrl/jd-bank/ui/queue"
Write-Host "`n  Note:" -ForegroundColor Cyan
Write-Info '  Ollama is NOT part of this bundle — it runs on aria-gb10-2 over the internal'
Write-Info '  network. The app, the dashboards and the funnel do not need it; `make embed`'
Write-Info '  and the LLM jobs do.'
Write-Host ''
