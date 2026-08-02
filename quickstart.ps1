<#
.SYNOPSIS
    Boot the whole JD Bank stack from a cold machine and report what you woke up to.

.DESCRIPTION
    One command to get from "just opened the repo" to "the app is up and the data is
    there". Builds the images, starts the long-running services, waits for them to be
    genuinely healthy (not merely started), applies the Postgres + Neo4j migrations,
    and prints a status block: ports, parser version, row counts, CAS mode, and whether
    the external Ollama host is reachable.

    DOCKER-ONLY (ADR-006). This script runs `docker compose` and nothing else — there is
    no host Python, venv, or pip anywhere in this project, and this script must never add
    one. Everything it invokes runs inside a container.

    WHAT IT STARTS: postgres, neo4j, redis, api, worker. That is "all containers" for
    normal use. It deliberately does NOT start gates/baseline/ingest/embed/cluster/etc —
    those are `profiles: ["tools"]` one-shot runners that exist to run a job and exit
    (`make gates`, `make ingest`, ...). Starting them would be wrong, not thorough.

    WHAT IT WILL NEVER START: Ollama. Inference runs on metal on `aria-gb10-2`, a trusted
    internal host (ADR-003, non-negotiable #5) — not on this box and not in Docker. The
    script only reports whether it is reachable, so an embed/LLM job fails fast and
    honestly rather than looking mysteriously broken.

.PARAMETER Rebuild
    Force `docker compose build` to re-run without cache. Use after changing
    core/requirements*.txt or the Dockerfile. This matters: `make gates` does NOT rebuild
    (it reuses a stale image), which once let a missing `jinja2` dependency pass locally
    and break CI. If dependencies moved, rebuild.

.PARAMETER SkipMigrate
    Skip the Postgres (alembic) + Neo4j (cypher) migrations. They are idempotent, so the
    only reason to skip is speed on a stack you know is current.

.PARAMETER NoCas
    Start the API with CAS SSO forced OFF for this run, regardless of .env. Gives you the
    frictionless dev-admin mode instead of an SFU login redirect. Does not edit .env.

.PARAMETER ArchivePath
    Path to the read-only SFU JD archive. Only the `tools` services bind it, so this is
    just exported for the follow-up commands the summary suggests (`make ingest`,
    `make baseline`). Never written to.

.PARAMETER Down
    Stop and remove the stack instead of starting it. Named volumes (pgdata, neo4jdata)
    are KEPT — your 14,522 parsed rows survive. Use `docker compose down -v` by hand if
    you genuinely want to lose them.

.EXAMPLE
    .\quickstart.ps1
    Cold boot: build, start, migrate, report.

.EXAMPLE
    .\quickstart.ps1 -NoCas
    Same, but skip the SFU CAS login so you land straight in the UI as a dev admin.

.EXAMPLE
    .\quickstart.ps1 -Rebuild -ArchivePath C:\repos\hris\fixtures\SFU_JDs
    Rebuild images after a dependency change and set the archive path for later jobs.

.EXAMPLE
    .\quickstart.ps1 -Down
    Stop everything, keep the data.
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$SkipMigrate,
    [switch]$NoCas,
    [string]$ArchivePath = $env:JD_ARCHIVE_PATH,
    [switch]$Down
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Run from the repo root no matter where the caller invoked us from.
Set-Location -LiteralPath $PSScriptRoot

# The host ports this project publishes. NOT the service defaults: this dev box runs
# several Docker projects at once and the standard ports are already taken, so claiming
# them makes `up` die with "port is already allocated". See the docker-compose.yml header.
$ApiPort   = if ($env:JD_API_PORT)        { $env:JD_API_PORT }        else { '25800' }
$PgPort    = if ($env:JD_PG_PORT)         { $env:JD_PG_PORT }         else { '25432' }
$Neo4jPort = if ($env:JD_NEO4J_HTTP_PORT) { $env:JD_NEO4J_HTTP_PORT } else { '25474' }
$RedisPort = if ($env:JD_REDIS_PORT)      { $env:JD_REDIS_PORT }      else { '25379' }

$Services = @('postgres', 'neo4j', 'redis', 'api', 'worker')

function Write-Step { param([string]$Text) Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  [ok]   $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  [warn] $Text" -ForegroundColor Yellow }
function Write-Info { param([string]$Text) Write-Host "  $Text" }

function Invoke-Compose {
    <#  Run `docker compose` and throw on a non-zero exit.

        $LASTEXITCODE is the only honest signal here: native executables do not trip
        PowerShell's ErrorActionPreference, so without this check a failed build or a
        port collision scrolls past and the script cheerfully reports success. #>
    param([Parameter(ValueFromRemainingArguments)][string[]]$ComposeArgs)
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') failed (exit $LASTEXITCODE)"
    }
}

# ── Preflight ───────────────────────────────────────────────────────────────
Write-Step 'Preflight'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker not found on PATH. Install Docker Desktop — this project has no host-Python fallback (ADR-006).'
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker is installed but not running. Start Docker Desktop and re-run.'
}
Write-Ok 'Docker daemon is up'

if (-not (Test-Path 'docker-compose.yml')) {
    throw "No docker-compose.yml in $PSScriptRoot — run this from the JD-Assistant repo root."
}

# ── Teardown mode ───────────────────────────────────────────────────────────
if ($Down) {
    Write-Step 'Stopping the stack'
    Invoke-Compose down
    Write-Ok 'Stopped. Named volumes (pgdata, neo4jdata) were KEPT — data is intact.'
    Write-Info 'To discard the data too: docker compose down -v'
    return
}

if ($ArchivePath) {
    if (Test-Path -LiteralPath $ArchivePath) {
        $env:JD_ARCHIVE_PATH = $ArchivePath
        Write-Ok "Archive path set for tool jobs: $ArchivePath (read-only)"
    }
    else {
        Write-Warn "Archive path not found, ignoring: $ArchivePath"
    }
}

# CAS is read from the gitignored .env. Overriding it here is a per-run env var, so the
# file is left alone — the next plain `docker compose up` goes back to whatever .env says.
if ($NoCas) {
    $env:CAS_ENABLED = 'false'
    Write-Ok 'CAS forced OFF for this run (dev-admin mode; .env not modified)'
}

# ── Build ───────────────────────────────────────────────────────────────────
Write-Step 'Building images'
if ($Rebuild) {
    Write-Info 'Rebuilding without cache (dependency or Dockerfile change)...'
    Invoke-Compose build --no-cache
}
else {
    # Quiet: a fully-cached build has nothing to say, and its layer chatter buries the
    # status block below. Failures still print — quiet suppresses progress, not errors.
    # `--progress` is a GLOBAL compose flag, so it goes before the subcommand.
    Invoke-Compose --progress quiet build
}
Write-Ok 'Images built'

# ── Start ───────────────────────────────────────────────────────────────────
Write-Step 'Starting services'
Write-Info "Starting: $($Services -join ', ')"
# --wait blocks until every service with a healthcheck reports healthy, so the migration
# step below cannot race a Postgres that is still starting up.
Invoke-Compose up -d --wait
Write-Ok 'All services report healthy'

# ── API readiness ───────────────────────────────────────────────────────────
# The API has no healthcheck in compose (it is a --reload uvicorn), so poll it here
# rather than assume "container running" means "app serving".
Write-Step 'Waiting for the API'
$apiUrl = "http://localhost:$ApiPort"
$ready = $false
foreach ($attempt in 1..30) {
    try {
        $resp = Invoke-WebRequest -Uri "$apiUrl/health" -TimeoutSec 3 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if ($ready) {
    Write-Ok "API answering on $apiUrl"
}
else {
    Write-Warn "API did not answer /health within ~60s. Check: docker compose logs api"
}

# ── Migrations ──────────────────────────────────────────────────────────────
if (-not $SkipMigrate) {
    Write-Step 'Applying migrations'

    Invoke-Compose exec -T api alembic upgrade head
    Write-Ok 'Postgres schema at head (alembic)'

    # Neo4j holds the JD vector index (768-dim cosine) + graph memory. Both cypher files
    # are idempotent, so re-running on a live stack is safe.
    foreach ($cypher in @('001_init.cypher', '002_jd_vectors.cypher')) {
        $path = Join-Path 'core/db/migrations' $cypher
        if (-not (Test-Path $path)) { Write-Warn "missing $path — skipped"; continue }
        Get-Content -LiteralPath $path -Raw |
            & docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass
        if ($LASTEXITCODE -ne 0) { throw "Neo4j migration $cypher failed (exit $LASTEXITCODE)" }
        Write-Ok "Neo4j $cypher applied"
    }
}
else {
    Write-Info 'Migrations skipped (-SkipMigrate)'
}

# ── Status ──────────────────────────────────────────────────────────────────
Write-Step 'Status'

& docker compose ps --format 'table {{.Service}}\t{{.Status}}'

# What data is actually in there? A stack that boots against an empty database looks
# identical to one with the full archive until you ask.
function Get-Scalar {
    <#  Run one query and return its rows, or $null if the query FAILED.

        Distinguishing "the query failed" from "the query returned nothing" is the whole
        point: the first cut of this swallowed stderr and reported a confident
        "parsed_jds is EMPTY" over a table holding 43,566 rows, because the SQL had a
        GROUP BY error. An empty result and a broken query must not look alike. #>
    param([string]$Query)
    $out = & docker compose exec -T postgres psql -U app -d harness -t -A -c $Query 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    # The leading comma keeps this an ARRAY through `return`. Without it PowerShell
    # unwraps a one-row result to a bare string, and indexing [0] then yields its first
    # CHARACTER — which is how a count of 1802 first rendered here as "1".
    return ,@($out | Where-Object { $_ -and "$_".Trim() })
}

Write-Host "`n  Data:" -ForegroundColor Cyan
$parsed = Get-Scalar 'SELECT parser_version || '' = '' || count(*) FROM parsed_jds GROUP BY parser_version ORDER BY parser_version;'
if ($null -eq $parsed) {
    Write-Warn '  Could not query parsed_jds (is the schema migrated?)'
}
elseif ($parsed.Count -eq 0) {
    Write-Warn '  parsed_jds is EMPTY — run: make ingest JD_ARCHIVE_PATH=<archive>'
}
else {
    foreach ($line in $parsed) { Write-Info "  parsed_jds  $("$line".Trim())" }
}

$canonical = Get-Scalar 'SELECT count(*) FROM canonical_jds;'
$canonicalCount = $canonical | Select-Object -First 1
if ($canonicalCount) {
    Write-Info "  canonical_jds (harmonized roles) = $("$canonicalCount".Trim())"
}

# Ollama lives outside this stack, on metal, on a trusted internal host. Report only.
Write-Host "`n  Inference host:" -ForegroundColor Cyan
$ollama = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { 'http://aria-gb10-2:11434/v1' }
try {
    $tags = $ollama -replace '/v1/?$', '/api/tags'
    $null = Invoke-WebRequest -Uri $tags -TimeoutSec 4 -UseBasicParsing
    Write-Ok "Ollama reachable at $ollama"
}
catch {
    Write-Warn "Ollama NOT reachable at $ollama"
    Write-Info '  Fine for the app, the dashboards and `make gates`. Embedding and LLM'
    Write-Info '  jobs (make embed / canonical-drafts) will fail until it is back.'
}

# Ask the RUNNING container, rather than inferring from .env plus the shell environment
# plus compose's precedence rules. Inference got this backwards on the first cut: -NoCas
# sets CAS_ENABLED=false (which compose honours over .env), but the check still found
# `CAS_ENABLED=true` in .env and reported SSO as ON while the app had it OFF.
$casEnv = (& docker compose exec -T api printenv CAS_ENABLED 2>$null | Select-Object -First 1)
$casOn = "$casEnv".Trim() -eq 'true'

Write-Host "`n  Open:" -ForegroundColor Cyan
Write-Info "  App          $apiUrl/jd-bank/ui/library     (JD Bank — browse roles)"
Write-Info "  Review queue $apiUrl/jd-bank/ui/queue"
Write-Info "  Dashboards   $apiUrl/jd-bank/ui/dashboard/baseline"
Write-Info "  Neo4j        http://localhost:$Neo4jPort  (neo4j / harnesspass)"
Write-Info "  Postgres     localhost:$PgPort  ·  Redis localhost:$RedisPort"
if ($casOn) {
    Write-Warn '  CAS SSO is ON — you will be redirected to cas.sfu.ca to sign in.'
    Write-Info '  For frictionless dev access instead: .\quickstart.ps1 -NoCas'
}
else {
    Write-Ok 'CAS is OFF — the UI is open in dev-admin mode.'
}

Write-Host "`n  Next:" -ForegroundColor Cyan
Write-Info '  make gates                                   full CI-identical suite'
Write-Info '  make ingest JD_ARCHIVE_PATH=<archive>        (re)parse the archive'
Write-Info '  .\quickstart.ps1 -Down                       stop, keep the data'
Write-Host ''
