<#
.SYNOPSIS
    Tests for deploy\BankTarget.ps1 — the resolver and the guard every script uses.

.DESCRIPTION
    Plain PowerShell asserts, no Pester (Windows ships Pester 3, CI's pwsh ships 5, and
    the two are not compatible). No Docker either: the guard is a pure function over
    the facts Docker would report, so each case states those facts directly.

    Run by `deploy/deploy-check.sh` (=> `make deploy-check`, CI's "Gate: deployable
    offline"). Exits non-zero on any failure.

        pwsh -NoProfile -File deploy/tests/bank-target.tests.ps1
#>
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot '../BankTarget.ps1')

$script:failures = 0
$script:passed = 0
function Check {
    param([string]$Name, [scriptblock]$Body)
    try {
        $ok = & $Body
        if ($ok -eq $true) { $script:passed++; Write-Host "  [ok]   $Name" }
        else { $script:failures++; Write-Host "  [FAIL] $Name  (got: $ok)" -ForegroundColor Red }
    }
    catch { $script:failures++; Write-Host "  [FAIL] $Name  (threw: $_)" -ForegroundColor Red }
}

# A scratch "checkout": a compose file carrying the default `name:`, and optionally a
# `.git` FILE (a linked worktree) or `.git` DIRECTORY (a main checkout).
function New-Checkout {
    param([switch]$Linked, [string]$DotEnv)
    $dir = Join-Path ([IO.Path]::GetTempPath()) ("banktarget-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $null = New-Item -ItemType Directory -Path $dir
    Set-Content -LiteralPath (Join-Path $dir 'docker-compose.yml') -Value "name: jd-bank`nservices: {}`n"
    if ($Linked) { Set-Content -LiteralPath (Join-Path $dir '.git') -Value 'gitdir: /elsewhere' }
    else { $null = New-Item -ItemType Directory -Path (Join-Path $dir '.git') }
    if ($DotEnv) { Set-Content -LiteralPath (Join-Path $dir '.env') -Value $DotEnv }
    return $dir
}

$liveDir = New-Checkout
$v9Env = "# a second bank`nCOMPOSE_PROJECT_NAME=jd-bank-v9`nJD_IMAGE_TAG=`"v9`"`nJD_API_PORT=26800 # inline comment`n"
$v9Dir = New-Checkout -Linked -DotEnv $v9Env
$bareWorktree = New-Checkout -Linked
$noTagDir = New-Checkout -Linked -DotEnv "COMPOSE_PROJECT_NAME=jd-bank-v9`n"

$none = @{}
$live = Resolve-BankTarget -Root $liveDir -Environment $none
$v9 = Resolve-BankTarget -Root $v9Dir -Environment $none
$bare = Resolve-BankTarget -Root $bareWorktree -Environment $none
$noTag = Resolve-BankTarget -Root $noTagDir -Environment $none

Write-Host "`n=== Resolution (env > .env > default — compose's own order) ==="
Check 'no .env: the live project and tag, the 25xxx ports' {
    $live.Project -eq 'jd-bank' -and $live.Tag -eq 'latest' -and $live.ApiPort -eq '25800' -and
    $live.PgPort -eq '25432' -and $live.ProjectSource -eq 'default'
}
Check 'the default project is READ from docker-compose.yml, not hardcoded' { $live.DefaultProject -eq 'jd-bank' }
Check '.env names the project and tag (quotes stripped)' {
    $v9.Project -eq 'jd-bank-v9' -and $v9.Tag -eq 'v9' -and $v9.ProjectSource -eq '.env'
}
Check '.env value with an inline comment is the value only' { $v9.ApiPort -eq '26800' }
Check 'keys .env does not set fall back to the defaults' { $v9.PgPort -eq '25432' }
Check 'the process environment beats .env' {
    $t = Resolve-BankTarget -Root $v9Dir -Environment @{ COMPOSE_PROJECT_NAME = 'from-shell' }
    $t.Project -eq 'from-shell' -and $t.ProjectSource -eq 'environment' -and $t.Tag -eq 'v9'
}
Check 'an EMPTY environment value does not count (compose ${X:-d} semantics)' {
    (Resolve-BankTarget -Root $v9Dir -Environment @{ COMPOSE_PROJECT_NAME = '' }).Project -eq 'jd-bank-v9'
}
Check 'a .git FILE marks a linked worktree; a .git DIRECTORY does not' {
    $v9.IsLinkedWorktree -and -not $live.IsLinkedWorktree
}

Write-Host "`n=== The guard ==="
$liveOwner = @($liveDir)
Check 'live checkout, its own running stack: allowed' {
    (Test-BankAction -Project 'jd-bank' -Target $live -Owners $liveOwner).Allowed
}
Check 'live checkout, -Volumes on its own stack: allowed' {
    (Test-BankAction -Project 'jd-bank' -Target $live -Owners $liveOwner -Destructive).Allowed
}
Check 'v9 checkout, -ProjectName jd-bank -Volumes while the live stack runs: REFUSED (ownership)' {
    $v = Test-BankAction -Project 'jd-bank' -Target $v9 -Owners $liveOwner -Destructive
    (-not $v.Allowed) -and $v.Reason -match 'another checkout'
}
Check 'v9 checkout, plain teardown of the live project: REFUSED (stopping is not harmless)' {
    -not (Test-BankAction -Project 'jd-bank' -Target $v9 -Owners $liveOwner).Allowed
}
Check 'ownership compares paths case- and slash-insensitively' {
    (Test-BankAction -Project 'jd-bank' -Target $live -Owners @($liveDir.ToUpperInvariant().Replace('\', '/'))).Allowed
}
Check 'v9 checkout, -ProjectName jd-bank -Volumes with the live stack DOWN: REFUSED (live name, worktree)' {
    -not (Test-BankAction -Project 'jd-bank' -Target $v9 -Destructive).Allowed
}
Check 'a linked worktree with NO .env cannot launch the live project name' {
    $v = Test-BankAction -Project 'jd-bank' -Target $bare
    (-not $v.Allowed) -and $v.Reason -match 'parallel-bank.env.example'
}
Check 'v9 checkout, its own project, nothing running yet: allowed' {
    (Test-BankAction -Project 'jd-bank-v9' -Target $v9 -Builds).Allowed
}
Check 'v9 checkout, -Volumes on its own project with only volumes left: allowed' {
    (Test-BankAction -Project 'jd-bank-v9' -Target $v9 -Destructive).Allowed
}
Check 'destructive action on a project that is not this checkout''s, no owner evidence: REFUSED' {
    -not (Test-BankAction -Project 'jd-bank-test' -Target $live -Destructive).Allowed
}
Check '...but allowed when this checkout created its containers (install -Isolated rehearsal)' {
    (Test-BankAction -Project 'jd-bank-test' -Target $live -Owners $liveOwner -Destructive).Allowed
}
Check 'a non-destructive action on a new project name (install -Isolated): allowed' {
    (Test-BankAction -Project 'jd-bank-test' -Target $live).Allowed
}
Check 'a second Bank still on tag latest: REFUSED to build (would overwrite the live images)' {
    $v = Test-BankAction -Project 'jd-bank-v9' -Target $noTag -Builds
    (-not $v.Allowed) -and $v.Reason -match 'JD_IMAGE_TAG'
}
Check 'building a tag another project''s containers run: REFUSED' {
    -not (Test-BankAction -Project 'jd-bank-v9' -Target $v9 -Builds -TagUsers @('jd-bank-v8-api-1')).Allowed
}
Check 'the live build is not blocked by a rehearsal sharing latest' {
    (Test-BankAction -Project 'jd-bank' -Target $live -Owners $liveOwner -Builds -TagUsers @('jd-bank-test-api-1')).Allowed
}
Check '-AllowForeignProject (typed by a person) overrides, and says so' {
    $v = Test-BankAction -Project 'jd-bank' -Target $v9 -Owners $liveOwner -Destructive -AllowForeignProject
    $v.Allowed -and $v.Reason -match 'bypassed'
}

Write-Host "`n=== The scripts actually use it, before they act ==="
$repo = Resolve-Path (Join-Path $PSScriptRoot '../..')
foreach ($pair in @(
        @{ f = 'teardown.ps1'; act = "'down'" },
        @{ f = 'launch.ps1'; act = 'Invoke-Compose up' },
        @{ f = 'build.ps1'; act = 'docker compose build' },
        @{ f = 'deploy/bundle.ps1'; act = 'docker compose stop neo4j' },
        @{ f = 'deploy/install.ps1'; act = "Invoke-Checked 'docker load'" }
    )) {
    Check "$($pair.f): guard runs before '$($pair.act)'" {
        $text = Get-Content -LiteralPath (Join-Path $repo $pair.f) -Raw
        $g = $text.IndexOf('Assert-BankAction ')
        $a = $text.IndexOf($pair.act)
        ($g -gt 0) -and ($a -gt $g)
    }
}
Check 'deploy/install.ps1: bundle image_tag is cross-checked BEFORE docker load' {
    $text = Get-Content -LiteralPath (Join-Path $repo 'deploy/install.ps1') -Raw
    $c = $text.IndexOf('$bundleTag -ne $Target.Tag')
    $a = $text.IndexOf("Invoke-Checked 'docker load'")
    ($c -gt 0) -and ($a -gt $c)
}
Check 'teardown.ps1 no longer defaults -ProjectName to a literal' {
    -not ((Get-Content -LiteralPath (Join-Path $repo 'teardown.ps1') -Raw) -match "\[string\]\`$ProjectName\s*=\s*'jd-bank'")
}

foreach ($d in @($liveDir, $v9Dir, $bareWorktree, $noTagDir)) { Remove-Item -LiteralPath $d -Recurse -Force }

Write-Host ''
if ($script:failures) {
    Write-Host "  BANK-TARGET TESTS: $script:failures FAILED, $script:passed passed" -ForegroundColor Red
    exit 1
}
Write-Host "  BANK-TARGET TESTS: all $script:passed passed" -ForegroundColor Green
exit 0
