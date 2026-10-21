<#
.SYNOPSIS
    Which JD Bank is this checkout about to act on — and may it?

.DESCRIPTION
    Dot-sourced by build.ps1, launch.ps1, teardown.ps1, deploy\bundle.ps1,
    deploy\install.ps1 and deploy\bank-target.ps1 (which `make` calls). ONE resolver,
    so no two scripts can disagree about which Bank they mean.

    WHY (P-stack, 2026-10-20). A second Bank runs from a second checkout beside the live
    one. Before this file, every script either hard-coded `jd-bank` (teardown, bundle)
    or relied on compose's `name: jd-bank` — so `teardown.ps1 -Volumes` typed in the
    second checkout destroyed the LIVE Bank, and `launch.ps1` there recreated the live
    containers with the other checkout's code (the api bind-mounts `./core`).

    RESOLUTION — the same precedence compose itself uses, for each key:
        1. the process environment (non-empty)
        2. the checkout's `.env` (git-ignored; one per checkout)
        3. the default (project: the compose file's `name:`; tag `latest`; 25xxx ports)
    Compose is then ASKED (`Assert-ComposeAgrees`) and a disagreement is a hard stop:
    a resolver that guesses differently from compose is worse than none.

    THE GUARD — `Test-BankAction`, a pure function so it is testable without Docker
    (deploy\tests\bank-target.tests.ps1, run by `make deploy-check`). In order:

      0. -AllowForeignProject, typed by a person, allows anything (loudly).
      1. OWNERSHIP. Compose stamps every container with the directory it was created
         from (`com.docker.compose.project.working_dir`). If the target project has
         long-running containers created from ANOTHER checkout, refuse. This is the
         rule that stops the v9 checkout touching the live stack, and it does not care
         about paths, branch names or worktrees — Docker records who owns what.
      2. THE LIVE NAME FROM A LINKED WORKTREE. When nothing is running there is no
         ownership to read, only volumes. So: the compose file's default project name
         (`jd-bank`) is reserved for a checkout that is NOT a linked git worktree. A
         linked worktree (`.git` is a file) must name its own project in `.env`.
         Chosen over "path is C:\repos\JD-Assistant on branch main" because paths
         differ per box (a fresh install is a copied repo anywhere) and the live
         checkout is routinely on a feature branch; and over a marker in `.env`
         because a marker can be copied along with the file it lives in.
      3. A DESTRUCTIVE action on a project that is not this checkout's own, with no
         container proving this checkout created it, refuses.
      4. TAG. A project other than the default still on tag `latest` refuses: its
         build would overwrite the live images.
#>

Set-StrictMode -Version Latest

$script:BankTargetKeys = [ordered]@{
    COMPOSE_PROJECT_NAME = $null      # default read from docker-compose.yml `name:`
    JD_IMAGE_TAG         = 'latest'
    JD_API_PORT          = '25800'
    JD_PG_PORT           = '25432'
    JD_NEO4J_HTTP_PORT   = '25474'
    JD_NEO4J_BOLT_PORT   = '25687'
    JD_REDIS_PORT        = '25379'
}

function Read-DotEnv {
    <#  KEY=VALUE lines of a compose-style `.env`. Comments, blanks, `export ` prefixes
        and surrounding quotes are handled; anything fancier (interpolation inside .env)
        is not used in this repo — and Assert-ComposeAgrees catches it if it ever is. #>
    param([string]$Path)
    $values = [ordered]@{}
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($raw in (Get-Content -LiteralPath $Path)) {
        $line = "$raw".Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        if ($line -match '^export\s+') { $line = $line -replace '^export\s+', '' }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if ($value.Length -ge 2 -and (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        elseif ($value -match '^(.*?)\s+#') { $value = $Matches[1].Trim() }
        $values[$key] = $value
    }
    return $values
}

function Get-ComposeDefaultProject {
    param([string]$Root)
    $file = Join-Path $Root 'docker-compose.yml'
    if (Test-Path -LiteralPath $file) {
        foreach ($line in (Get-Content -LiteralPath $file -TotalCount 20)) {
            if ($line -match '^name:\s*(\S+)\s*$') { return $Matches[1] }
        }
    }
    return 'jd-bank'
}

function ConvertTo-NormalPath {
    param([string]$Path)
    if (-not $Path) { return '' }
    $p = $Path -replace '\\', '/'
    return $p.TrimEnd('/').ToLowerInvariant()
}

function Resolve-BankTarget {
    <#  The Bank this checkout means. -Environment / -DotEnv are injectable for tests;
        by default they are the live process environment and `<Root>\.env`. #>
    param(
        [Parameter(Mandatory)][string]$Root,
        [System.Collections.IDictionary]$Environment,
        [System.Collections.IDictionary]$DotEnv
    )
    if ($null -eq $Environment) {
        $Environment = @{}
        foreach ($k in $script:BankTargetKeys.Keys) {
            $v = [Environment]::GetEnvironmentVariable($k)
            if ($v) { $Environment[$k] = $v }
        }
    }
    if ($null -eq $DotEnv) { $DotEnv = Read-DotEnv (Join-Path $Root '.env') }

    $defaultProject = Get-ComposeDefaultProject $Root
    $values = [ordered]@{}
    $sources = [ordered]@{}
    foreach ($k in $script:BankTargetKeys.Keys) {
        $default = if ($k -eq 'COMPOSE_PROJECT_NAME') { $defaultProject } else { $script:BankTargetKeys[$k] }
        if ($Environment.Contains($k) -and "$($Environment[$k])") {
            $values[$k] = "$($Environment[$k])"; $sources[$k] = 'environment'
        }
        elseif ($DotEnv.Contains($k) -and "$($DotEnv[$k])") {
            $values[$k] = "$($DotEnv[$k])"; $sources[$k] = '.env'
        }
        else { $values[$k] = $default; $sources[$k] = 'default' }
    }

    $gitPath = Join-Path $Root '.git'
    $linked = (Test-Path -LiteralPath $gitPath -PathType Leaf)

    return [pscustomobject]@{
        Root             = $Root
        Project          = $values['COMPOSE_PROJECT_NAME']
        ProjectSource    = $sources['COMPOSE_PROJECT_NAME']
        DefaultProject   = $defaultProject
        Tag              = $values['JD_IMAGE_TAG']
        TagSource        = $sources['JD_IMAGE_TAG']
        ApiPort          = $values['JD_API_PORT']
        PgPort           = $values['JD_PG_PORT']
        Neo4jHttpPort    = $values['JD_NEO4J_HTTP_PORT']
        Neo4jBoltPort    = $values['JD_NEO4J_BOLT_PORT']
        RedisPort        = $values['JD_REDIS_PORT']
        IsLinkedWorktree = [bool]$linked
        Sources          = $sources
    }
}

function Write-BankTarget {
    <#  Say which Bank, BEFORE acting. Every script calls this first. #>
    param([Parameter(Mandatory)]$Target, [string]$Project)
    $p = if ($Project) { $Project } else { $Target.Project }
    $live = if ($p -eq $Target.DefaultProject) { '   <- the LIVE project name' } else { '' }
    Write-Host ''
    Write-Host '  Acting on JD Bank:' -ForegroundColor Cyan
    Write-Host ("    project  {0,-22} ({1}){2}" -f $p, $(if ($Project -and $Project -ne $Target.Project) { 'typed -ProjectName' } else { $Target.ProjectSource }), $live)
    Write-Host ("    images   jd-bank-api:{0} / jd-bank-worker:{0}  ({1})" -f $Target.Tag, $Target.TagSource)
    Write-Host ("    ports    api {0} · postgres {1} · neo4j {2}/{3} · redis {4}" -f $Target.ApiPort, $Target.PgPort, $Target.Neo4jHttpPort, $Target.Neo4jBoltPort, $Target.RedisPort)
    Write-Host ("    checkout {0}{1}" -f $Target.Root, $(if ($Target.IsLinkedWorktree) { '  (linked git worktree)' } else { '' }))
}

function Get-ProjectOwner {
    <#  The checkout directories that created the project's LONG-RUNNING containers.
        One-off `run` containers are excluded: `make smoke` from a worktree legitimately
        runs a one-off in the live project, and that must not make the worktree an
        "owner" of the live Bank. #>
    param([Parameter(Mandatory)][string]$Project)
    $dirs = @(& docker ps -a --filter "label=com.docker.compose.project=$Project" `
            --filter 'label=com.docker.compose.oneoff=False' `
            --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>$null |
            Where-Object { $_ } | Sort-Object -Unique)
    return , $dirs
}

function Get-TagUser {
    <#  Other projects' containers running jd-bank-api:<tag> / jd-bank-worker:<tag>. #>
    param([Parameter(Mandatory)][string]$Tag, [Parameter(Mandatory)][string]$Project)
    $users = @()
    foreach ($img in @("jd-bank-api:$Tag", "jd-bank-worker:$Tag")) {
        $rows = @(& docker ps -a --filter "ancestor=$img" `
                --format '{{.Names}} {{.Label "com.docker.compose.project"}}' 2>$null | Where-Object { $_ })
        foreach ($r in $rows) {
            $parts = "$r".Split(' ')
            if ($parts.Count -ge 2 -and $parts[1] -and $parts[1] -ne $Project) { $users += $parts[0] }
        }
    }
    return , @($users | Sort-Object -Unique)
}

function Test-BankAction {
    <#  The guard, as a pure decision. Returns [pscustomobject]@{ Allowed; Reason }. #>
    param(
        [Parameter(Mandatory)][string]$Project,
        [Parameter(Mandatory)]$Target,
        [string[]]$Owners = @(),
        [switch]$Destructive,
        [switch]$Builds,
        [string[]]$TagUsers = @(),
        [switch]$AllowForeignProject
    )
    $Owners = @($Owners | Where-Object { $_ })
    $TagUsers = @($TagUsers | Where-Object { $_ })
    if ($AllowForeignProject) {
        return [pscustomobject]@{ Allowed = $true; Reason = "-AllowForeignProject typed: guard bypassed for '$Project'." }
    }
    $here = ConvertTo-NormalPath $Target.Root
    $foreign = @($Owners | Where-Object { (ConvertTo-NormalPath $_) -ne $here })
    if ($foreign) {
        return [pscustomobject]@{ Allowed = $false; Reason = (
                "project '$Project' belongs to another checkout: its containers were created from " +
                "$($foreign -join ', '), not $($Target.Root). Run this from THAT checkout. " +
                "(-AllowForeignProject overrides; think first.)") }
    }
    if ($Project -eq $Target.DefaultProject -and $Target.IsLinkedWorktree -and -not $Owners) {
        return [pscustomobject]@{ Allowed = $false; Reason = (
                "'$Project' is the LIVE project name and this checkout is a linked git worktree. " +
                "A second checkout must name its own Bank: copy deploy\parallel-bank.env.example " +
                "to $(Join-Path $Target.Root '.env') and set COMPOSE_PROJECT_NAME / JD_IMAGE_TAG / ports.") }
    }
    if ($Destructive -and $Project -ne $Target.Project -and -not $Owners) {
        return [pscustomobject]@{ Allowed = $false; Reason = (
                "refusing a DESTRUCTIVE action on '$Project': this checkout's project is " +
                "'$($Target.Project)', and no container shows '$Project' was created from here. " +
                "(-AllowForeignProject overrides; think first.)") }
    }
    if ($Builds -and $Project -ne $Target.DefaultProject -and $Target.Tag -eq 'latest') {
        return [pscustomobject]@{ Allowed = $false; Reason = (
                "project '$Project' is not the live one but its image tag is 'latest' — the LIVE " +
                "images. A build here would overwrite them. Set JD_IMAGE_TAG in $(Join-Path $Target.Root '.env').") }
    }
    # The live checkout owns `latest`: an `install.ps1 -Isolated` rehearsal shares those
    # images by design and must not block the live build.
    $liveOwnTag = ($Project -eq $Target.DefaultProject -and $Target.Tag -eq 'latest')
    if ($Builds -and $TagUsers -and -not $liveOwnTag) {
        return [pscustomobject]@{ Allowed = $false; Reason = (
                "image tag '$($Target.Tag)' is in use by another project's containers ($($TagUsers -join ', ')). " +
                "A build here would replace the images under them. Set a different JD_IMAGE_TAG.") }
    }
    return [pscustomobject]@{ Allowed = $true; Reason = "ok: '$Project' is this checkout's to act on." }
}

function Assert-ComposeAgrees {
    <#  Ask compose which project and app image it resolves, and stop if the resolver
        above disagrees. This is what makes "the SAME way compose does" a checked fact. #>
    param([Parameter(Mandatory)]$Target, [string]$Project)
    $p = if ($Project) { $Project } else { $Target.Project }
    $pre = if ($Project) { @('--project-name', $Project) } else { @() }
    $cfg = $null
    try { $cfg = (& docker compose @pre config --format json 2>$null | Out-String | ConvertFrom-Json) } catch { $cfg = $null }
    if (-not $cfg) { throw 'Could not read `docker compose config` to cross-check the target.' }
    $problems = @()
    if ($cfg.name -ne $p) { $problems += "project: compose says '$($cfg.name)', resolver says '$p'" }
    $apiImage = $cfg.services.api.image
    if ($apiImage -ne "jd-bank-api:$($Target.Tag)") { $problems += "api image: compose says '$apiImage', resolver says 'jd-bank-api:$($Target.Tag)'" }
    if ($problems) { throw ("The bank-target resolver disagrees with docker compose — refusing to act. " + ($problems -join '; ')) }
}

function Assert-BankAction {
    <#  Resolve-and-guard in one call for the scripts. Throws on a refusal. #>
    param(
        [Parameter(Mandatory)]$Target,
        [string]$Project,
        [switch]$Destructive,
        [switch]$Builds,
        [switch]$AllowForeignProject
    )
    $p = if ($Project) { $Project } else { $Target.Project }
    $owners = Get-ProjectOwner -Project $p
    $tagUsers = if ($Builds) { Get-TagUser -Tag $Target.Tag -Project $p } else { @() }
    $verdict = Test-BankAction -Project $p -Target $Target -Owners $owners -TagUsers $tagUsers `
        -Destructive:$Destructive -Builds:$Builds -AllowForeignProject:$AllowForeignProject
    if (-not $verdict.Allowed) {
        Write-Host "  [REFUSED] $($verdict.Reason)" -ForegroundColor Red
        throw "Refused by the bank-target guard: $($verdict.Reason)"
    }
    if ($AllowForeignProject) { Write-Host "  [warn] $($verdict.Reason)" -ForegroundColor Yellow }
    else { Write-Host "  [ok]   guard: $($verdict.Reason)" -ForegroundColor Green }
}
