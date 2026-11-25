<#
.SYNOPSIS
  Package the VPFA handoff bundle: put a snapshot in it, refresh the parent git bundle,
  hash every file, and zip it with a checksum. START-HERE.md Part A, step A5.

.EXAMPLE
  .\tools\package.ps1 -Snapshot C:\repos\jd-bank-snapshots\v9-2026-11-25
#>
param(
  [Parameter(Mandatory)] [string] $Snapshot,                  # a folder holding manifest.json
  [string] $Bundle = (Split-Path $PSScriptRoot -Parent),      # this bundle's root
  [string] $ParentRepo = 'C:\repos\JD-Assistant'               # where main + origin/bank/v9 live
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path (Join-Path $Snapshot 'manifest.json'))) { throw "no manifest.json in $Snapshot" }

# 1. The snapshot: exactly one, under snapshot\<name>\
$dest = Join-Path $Bundle 'snapshot'
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
New-Item -ItemType Directory $dest | Out-Null
Copy-Item -Recurse $Snapshot $dest
$name = Split-Path $Snapshot -Leaf

# Check the copy against the snapshot's own manifest before going further.
$m = Get-Content (Join-Path $dest "$name\manifest.json") -Raw | ConvertFrom-Json
foreach ($p in $m.files.PSObject.Properties) {
  $h = (Get-FileHash -Algorithm SHA256 (Join-Path $dest "$name\$($p.Name)")).Hash.ToLower()
  if ($h -ne $p.Value.sha256) { throw "snapshot file $($p.Name) does not match its manifest" }
}

# 2. The parent source: main + bank/v9, full history.
# Through a throwaway bare repo, so the bundle carries real branches (refs/heads/main and
# refs/heads/bank/v9) that a clone can check out. Bundling origin/* would clone empty.
git -C $ParentRepo fetch -q origin
$gb = Join-Path $Bundle 'parent\jd-assistant.bundle'
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Bundle 'parent\*.bundle')
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("vpfa-bundle-" + [guid]::NewGuid())
git init -q --bare $tmp
git -C $ParentRepo push -q $tmp 'refs/remotes/origin/main:refs/heads/main' 'refs/remotes/origin/bank/v9:refs/heads/bank/v9'
git -C $tmp bundle create $gb main bank/v9 2>$null
git -C $tmp bundle verify $gb | Out-Null
$ok = $LASTEXITCODE
Remove-Item -Recurse -Force $tmp
if ($ok -ne 0) { throw 'git bundle failed to verify' }

# 3. Hash every file.
Push-Location $Bundle
$lines = Get-ChildItem -Recurse -File | Where-Object Name -ne 'SHA256SUMS' | Sort-Object FullName |
  ForEach-Object {
    $rel = $_.FullName.Substring($Bundle.Length + 1).Replace('\', '/')
    '{0}  {1}' -f (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower(), $rel
  }
[IO.File]::WriteAllLines((Join-Path $Bundle 'SHA256SUMS'), $lines)
Pop-Location

# 4. Zip + checksum, beside the bundle folder.
$zip = "$Bundle-$name.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $Bundle -DestinationPath $zip -CompressionLevel Optimal
$zh = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
"$zh  $(Split-Path $zip -Leaf)" | Set-Content "$zip.sha256"

'snapshot : {0} ({1} drafts, parser {2})' -f $name, ($m.files.'canonical_jds.jsonl'.rows), $m.parser_version
'parent   : {0}' -f ((git bundle list-heads $gb) -join '; ')
'zip      : {0} ({1:N0} MB)' -f $zip, ((Get-Item $zip).Length / 1MB)
'sha256   : {0}' -f $zh
