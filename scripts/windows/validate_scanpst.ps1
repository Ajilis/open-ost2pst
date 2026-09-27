param(
    [Parameter(Mandatory = $true)]
    [string]$PstPath,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [string]$ScanPstPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Find-ScanPst {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        $resolved = Resolve-Path -LiteralPath $ExplicitPath -ErrorAction SilentlyContinue
        if ($resolved) {
            return $resolved.Path
        }
        throw "SCANPST.EXE not found at explicit path: $ExplicitPath"
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")

    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles "Microsoft Office\root\Office16\SCANPST.EXE"))
        $candidates.Add((Join-Path $env:ProgramFiles "Microsoft Office\Office16\SCANPST.EXE"))
    }

    if ($programFilesX86) {
        $candidates.Add((Join-Path $programFilesX86 "Microsoft Office\root\Office16\SCANPST.EXE"))
        $candidates.Add((Join-Path $programFilesX86 "Microsoft Office\Office16\SCANPST.EXE"))
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    foreach ($root in @($env:ProgramFiles, $programFilesX86)) {
        if (-not $root) {
            continue
        }
        $officeRoot = Join-Path $root "Microsoft Office"
        if (-not (Test-Path -LiteralPath $officeRoot)) {
            continue
        }

        $match = Get-ChildItem -LiteralPath $officeRoot -Filter "SCANPST.EXE" -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }

    throw "SCANPST.EXE was not found. Install classic Microsoft Outlook/Office on this runner."
}

$pst = (Resolve-Path -LiteralPath $PstPath).Path
$scanpst = Find-ScanPst -ExplicitPath $ScanPstPath

$reportFullPath = [System.IO.Path]::GetFullPath($ReportPath)
$reportDirectory = Split-Path -Parent $reportFullPath
if ($reportDirectory) {
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
}

$tempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("open-ost2pst-scanpst-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDirectory -Force | Out-Null

$validationPst = Join-Path $tempDirectory "interop.pst"
$backupPath = Join-Path $tempDirectory "interop.bak"
Copy-Item -LiteralPath $pst -Destination $validationPst -Force

$beforeHash = (Get-FileHash -LiteralPath $validationPst -Algorithm SHA256).Hash

$arguments = @(
    "-silent",
    "-force",
    "-rescan",
    "1",
    "-log",
    "replace",
    "-backupfile",
    ('"{0}"' -f $backupPath),
    "-file",
    ('"{0}"' -f $validationPst)
)

$process = Start-Process -FilePath $scanpst -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
$afterHash = (Get-FileHash -LiteralPath $validationPst -Algorithm SHA256).Hash

$changed = $beforeHash -ne $afterHash
$backupExists = Test-Path -LiteralPath $backupPath

$logFiles = @(
    Get-ChildItem -LiteralPath $tempDirectory -Filter "*.log" -File -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
)

$logText = @()
foreach ($logFile in $logFiles) {
    $logText += Get-Content -LiteralPath $logFile -Raw -ErrorAction SilentlyContinue
}

$errors = New-Object System.Collections.Generic.List[string]
if ($process.ExitCode -ne 0) {
    $errors.Add("SCANPST exited with code $($process.ExitCode)")
}
if ($changed) {
    $errors.Add("SCANPST modified the validation copy; repairs were required")
}
if ($backupExists) {
    $errors.Add("SCANPST created a backup file; repairs were required")
}
if ($logFiles.Count -eq 0) {
    $errors.Add("SCANPST did not create a log file")
}

$report = [ordered]@{
    validator = "scanpst"
    status = $(if ($errors.Count -eq 0) { "ok" } else { "failed" })
    input_pst = $pst
    validation_copy = $validationPst
    scanpst_path = $scanpst
    exit_code = $process.ExitCode
    sha256_before = $beforeHash
    sha256_after = $afterHash
    file_changed = $changed
    backup_created = $backupExists
    log_files = $logFiles
    log_text = $logText
    errors = @($errors)
}

$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportFullPath -Encoding UTF8

if ($errors.Count -ne 0) {
    foreach ($errorMessage in $errors) {
        Write-Error $errorMessage
    }
    exit 1
}

Write-Host "SCANPST validation passed without modifying the PST copy."
exit 0
