<#
.SYNOPSIS
    Cut a self-contained offline deployment bundle of the whole JD Bank.

.DESCRIPTION
    Produces ONE directory a fresh box can install from with NO internet: every
    container image, the full Postgres Bank, and the Neo4j vector store.

    Run this on a CONNECTED box (it builds images and pulls base images).
    `install.ps1` then runs on the target and never touches the network.

    WHAT GOES IN, AND WHY EACH IS NEEDED OFFLINE
      images.tar     All images compose requires. A fresh box cannot reach Docker Hub
                     for postgres/neo4j/redis, and cannot reach PyPI to `pip install`
                     the api image's dependencies. Shipping built images removes both.
                     (APOC is NOT a worry: neo4j:5-community carries apoc-core in
                     /var/lib/neo4j/labs and NEO4J_PLUGINS copies it locally — verified
                     on 2026-08-28, not assumed.)
      postgres.dump  `pg_dump -Fc` of `harness` — the whole relational Bank.
      neo4j.dump     `neo4j-admin database dump` of `neo4j` — the vector store. Neo4j is
                     a DERIVED index and could be rebuilt with `make embed` /
                     `make embed-roles`, but that costs GPU hours on aria-gb10-2.
                     Shipping it makes the target useful the moment it boots.
      MANIFEST.txt   Image ids, row counts and SHA-256 of every artifact, so the target
                     can prove it installed what we cut.

    WHAT IS NOT IN IT, ON PURPOSE
      The repo. `api`/`worker` bind-mount `./core`, so the SOURCE is what the app runs —
      copy the repo to the target alongside this bundle. That is also why a CODE change
      does not require re-cutting the bundle: only a dependency or Dockerfile change does.

      Ollama. It runs on metal on `aria-gb10-2` (ADR-003, non-negotiable #5), reachable
      over the internal network. Nothing here bundles a model.

.PARAMETER OutDir
    Where to write the bundle. Default: .\dist\jd-bank-bundle

.PARAMETER SkipImages
    Skip the image tarball — the slow, large part. For re-cutting just the data.

.PARAMETER SkipData
    Skip the Postgres + Neo4j dumps. For re-cutting just the images after a dependency
    change.

.EXAMPLE
    .\deploy\bundle.ps1
    Full bundle: build, save images, dump both databases, write the manifest.
#>
[CmdletBinding()]
param(
    [string]$OutDir = (Join-Path $PSScriptRoot '..\dist\jd-bank-bundle'),
    [switch]$SkipImages,
    [switch]$SkipData
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')

function Write-Step { param([string]$T) Write-Host "`n=== $T ===" -ForegroundColor Cyan }
function Write-Ok { param([string]$T) Write-Host "  [ok]   $T" -ForegroundColor Green }
function Write-Warn { param([string]$T) Write-Host "  [warn] $T" -ForegroundColor Yellow }
function Write-Info { param([string]$T) Write-Host "  $T" }

function Invoke-Checked {
    <#  Run a native command and throw on non-zero.

        $LASTEXITCODE is the only honest signal here: native executables do not trip
        PowerShell's ErrorActionPreference, so without this check a failed dump scrolls
        past and the bundle is silently short a file. #>
    param([string]$What, [scriptblock]$Body)
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

function Format-Mb { param([long]$Bytes) return ('{0:N0}' -f ($Bytes / 1MB)) }

# The images compose actually needs, ASKED OF COMPOSE rather than hardcoded — a service
# added to docker-compose.yml cannot then be silently left out of the bundle.
$Images = @(& docker compose config --images 2>$null | Sort-Object -Unique | Where-Object { $_ })
if (-not $Images) { throw 'Could not read the image list from docker compose.' }

Write-Step 'Preflight'
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running.' }
Write-Ok 'Docker daemon is up'
Write-Info "Images compose requires: $($Images -join ', ')"

$null = New-Item -ItemType Directory -Force -Path $OutDir
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path
Write-Ok "Bundle directory: $OutDir"

# ── Images ──────────────────────────────────────────────────────────────────
if (-not $SkipImages) {
    Write-Step 'Building images'
    # Built, not merely pulled: the api/worker images must carry the CURRENT
    # requirements.txt, or the target installs an app whose dependencies do not match
    # the source it will bind-mount.
    Invoke-Checked 'docker compose build' { & docker compose --progress quiet build }
    Write-Ok 'api/worker images built from current requirements'

    Write-Step 'Fetching base images'
    # Only the third-party ones. A plain `docker compose pull` would also try to pull the
    # locally-built api/worker and fail; --ignore-buildable skips exactly those.
    & docker compose pull --ignore-buildable --quiet 2>&1 | Out-Null
    Write-Ok 'Base images present locally'

    Write-Step 'Saving images'
    Write-Info 'The slow part — roughly 2.2 GB of layers.'
    $tar = Join-Path $OutDir 'images.tar'
    Invoke-Checked 'docker save' { & docker save -o $tar @Images }
    Write-Ok "images.tar written ($(Format-Mb (Get-Item $tar).Length) MB)"
}
else { Write-Info 'Images skipped (-SkipImages)' }

# ── Data ────────────────────────────────────────────────────────────────────
if (-not $SkipData) {
    Write-Step 'Dumping Postgres'
    $pgId = (& docker compose ps -q postgres 2>$null)
    if (-not $pgId) { throw 'postgres is not running — start the stack before cutting a data bundle.' }
    $pgId = "$pgId".Trim()

    # -Fc (custom format) of the WHOLE database, never --data-only. The archived trap:
    # `pg_restore --data-only` into an already-migrated database SILENTLY DESTROYS the
    # Bank and exits 0. A full custom-format dump restored into an EMPTY database is the
    # only path install.ps1 will take.
    $dump = Join-Path $OutDir 'postgres.dump'
    Invoke-Checked 'pg_dump' {
        & docker compose exec -T postgres pg_dump -U app -d harness -Fc --no-owner --no-acl -f /tmp/jdbank.dump
    }
    Invoke-Checked 'docker cp (postgres dump)' { & docker cp "${pgId}:/tmp/jdbank.dump" $dump }
    & docker compose exec -T postgres rm -f /tmp/jdbank.dump 2>&1 | Out-Null
    Write-Ok "postgres.dump written ($(Format-Mb (Get-Item $dump).Length) MB)"

    Write-Step 'Dumping Neo4j'
    # `neo4j-admin database dump` requires the database STOPPED, so the container comes
    # down and a one-off container of the same image dumps the volume.
    $project = 'jd-bank'
    try {
        $cfg = (& docker compose config --format json 2>$null | ConvertFrom-Json)
        if ($cfg.name) { $project = $cfg.name }
    }
    catch { Write-Warn "Could not read the compose project name; assuming '$project'." }
    $vol = "${project}_neo4jdata"
    $neo4jImage = $Images | Where-Object { $_ -like 'neo4j:*' } | Select-Object -First 1
    if (-not $neo4jImage) { throw 'No neo4j image in the compose image list.' }

    Write-Info 'Stopping neo4j (the dump requires the database offline)...'
    Invoke-Checked 'docker compose stop neo4j' { & docker compose stop neo4j }
    try {
        Invoke-Checked 'neo4j-admin database dump' {
            & docker run --rm -v "${vol}:/data" -v "${OutDir}:/dumps" $neo4jImage `
                neo4j-admin database dump neo4j --to-path=/dumps --overwrite-destination=true
        }
    }
    finally {
        # Always bring it back, even if the dump threw: leaving the operator's stack down
        # is a worse failure than a missing dump.
        & docker compose start neo4j 2>&1 | Out-Null
        Write-Info 'neo4j restarted'
    }
    $neoDump = Join-Path $OutDir 'neo4j.dump'
    if (-not (Test-Path -LiteralPath $neoDump)) {
        throw "neo4j-admin reported success but $neoDump is missing."
    }
    Write-Ok "neo4j.dump written ($(Format-Mb (Get-Item $neoDump).Length) MB)"
}
else { Write-Info 'Data skipped (-SkipData)' }

# ── Manifest ────────────────────────────────────────────────────────────────
Write-Step 'Writing manifest'

function Get-Scalar {
    <#  One scalar from Postgres, or $null if the QUERY FAILED.

        Telling "the query failed" apart from "the query returned nothing" is the whole
        point: a broken query must never render as a confident zero. #>
    param([string]$Query)
    $out = & docker compose exec -T postgres psql -U app -d harness -t -A -c $Query 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    return ("$($out | Select-Object -First 1)").Trim()
}

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('JD Bank offline bundle')
$lines.Add("cut_at_utc    : $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))")
$lines.Add("cut_from_host : $env:COMPUTERNAME")
$lines.Add("git_commit    : $(& git rev-parse HEAD 2>$null)")
$lines.Add("git_branch    : $(& git rev-parse --abbrev-ref HEAD 2>$null)")
$dirty = & git status --porcelain 2>$null
$lines.Add("git_dirty     : $(if ($dirty) { 'YES - bundle does not match a commit' } else { 'no' })")
$lines.Add('')
$lines.Add('images (name -> local image id):')
foreach ($img in $Images) {
    $id = & docker image inspect $img --format '{{.Id}}' 2>$null
    $lines.Add(('  {0,-22} {1}' -f $img, $(if ($id) { "$id".Trim() } else { 'NOT PRESENT LOCALLY' })))
}
$lines.Add('')
$lines.Add('data (row counts at cut time - install.ps1 re-checks these):')
foreach ($pair in @(
        @{ n = 'source_documents'; q = 'SELECT count(*) FROM source_documents;' },
        @{ n = 'parsed_jds'; q = 'SELECT count(*) FROM parsed_jds;' },
        @{ n = 'canonical_jds'; q = 'SELECT count(*) FROM canonical_jds;' },
        @{ n = 'clusters'; q = 'SELECT count(*) FROM clusters;' },
        @{ n = 'dedup_edges'; q = 'SELECT count(*) FROM dedup_edges;' }
    )) {
    $v = Get-Scalar $pair.q
    $lines.Add(('  {0,-22} {1}' -f $pair.n, $(if ($null -eq $v) { 'QUERY FAILED' } else { $v })))
}
$lines.Add('')
$lines.Add('artifacts (SHA-256):')
$artifacts = Get-ChildItem -LiteralPath $OutDir -File |
    Where-Object { $_.Name -ne 'MANIFEST.txt' } | Sort-Object Name
foreach ($f in $artifacts) {
    $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    $lines.Add(('  {0,-16} {1,8} MB  {2}' -f $f.Name, (Format-Mb $f.Length), $h))
}

$manifest = Join-Path $OutDir 'MANIFEST.txt'
($lines -join "`n") | Set-Content -LiteralPath $manifest -Encoding UTF8
Write-Ok 'MANIFEST.txt written'

# ── Summary ─────────────────────────────────────────────────────────────────
Write-Step 'Bundle ready'
$all = Get-ChildItem -LiteralPath $OutDir -File | Sort-Object Name
foreach ($f in $all) { Write-Info ('  {0,-16} {1,8} MB' -f $f.Name, (Format-Mb $f.Length)) }
$total = ($all | Measure-Object -Property Length -Sum).Sum
Write-Info ''
Write-Info ('  TOTAL            {0,8} MB' -f (Format-Mb $total))

Write-Host "`n  To deploy:" -ForegroundColor Cyan
Write-Info '  1. Copy the REPO and this bundle directory to the target box.'
Write-Info '  2. On the target:  .\deploy\install.ps1 -BundleDir <bundle>'
Write-Info ''
Write-Info '  The target needs no internet. It does need the internal network if you'
Write-Info '  want `make embed` or LLM jobs (Ollama on aria-gb10-2).'
Write-Host ''
