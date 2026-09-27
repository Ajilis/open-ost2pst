param(
    [Parameter(Mandatory = $true)]
    [string]$PstPath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedManifest,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Release-ComObject {
    param([object]$Object)
    if ($null -ne $Object -and [System.Runtime.InteropServices.Marshal]::IsComObject($Object)) {
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($Object)
    }
}

function Normalize-Path {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd("\").ToLowerInvariant()
}

function Find-StoreByPath {
    param(
        [object]$Namespace,
        [string]$TargetPath
    )

    $normalizedTarget = Normalize-Path $TargetPath

    for ($index = 1; $index -le $Namespace.Stores.Count; $index++) {
        $store = $Namespace.Stores.Item($index)
        $keep = $false
        try {
            if (-not $store.IsDataFileStore) {
                continue
            }

            $filePath = [string]$store.FilePath
            if ([string]::IsNullOrWhiteSpace($filePath)) {
                continue
            }

            if ((Normalize-Path $filePath) -eq $normalizedTarget) {
                $keep = $true
                return $store
            }
        }
        catch {
            # Provider-backed stores can reject FilePath or IsDataFileStore.
        }
        finally {
            if (-not $keep) {
                Release-ComObject $store
            }
        }
    }

    return $null
}

function Walk-Folder {
    param(
        [object]$Folder,
        [ref]$FolderCount,
        [ref]$MessageCount,
        [ref]$AttachmentCount,
        [System.Collections.Generic.List[string]]$Subjects,
        [System.Collections.Generic.List[string]]$FolderNames
    )

    $FolderCount.Value++
    $FolderNames.Add([string]$Folder.Name)

    $items = $Folder.Items
    try {
        $MessageCount.Value += $items.Count

        for ($itemIndex = 1; $itemIndex -le $items.Count; $itemIndex++) {
            $item = $items.Item($itemIndex)
            try {
                try {
                    $Subjects.Add([string]$item.Subject)
                }
                catch {
                    $Subjects.Add("")
                }

                try {
                    $attachments = $item.Attachments
                    try {
                        $AttachmentCount.Value += $attachments.Count
                    }
                    finally {
                        Release-ComObject $attachments
                    }
                }
                catch {
                    # Non-mail items may not expose Attachments.
                }
            }
            finally {
                Release-ComObject $item
            }
        }
    }
    finally {
        Release-ComObject $items
    }

    $folders = $Folder.Folders
    try {
        for ($folderIndex = 1; $folderIndex -le $folders.Count; $folderIndex++) {
            $child = $folders.Item($folderIndex)
            try {
                Walk-Folder -Folder $child -FolderCount $FolderCount -MessageCount $MessageCount -AttachmentCount $AttachmentCount -Subjects $Subjects -FolderNames $FolderNames
            }
            finally {
                Release-ComObject $child
            }
        }
    }
    finally {
        Release-ComObject $folders
    }
}

$pst = (Resolve-Path -LiteralPath $PstPath).Path
$expectedPath = (Resolve-Path -LiteralPath $ExpectedManifest).Path
$expected = Get-Content -LiteralPath $expectedPath -Raw -Encoding UTF8 | ConvertFrom-Json

$reportFullPath = [System.IO.Path]::GetFullPath($ReportPath)
$reportDirectory = Split-Path -Parent $reportFullPath
if ($reportDirectory) {
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
}

$tempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("open-ost2pst-outlook-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDirectory -Force | Out-Null
$validationPst = Join-Path $tempDirectory "interop.pst"
Copy-Item -LiteralPath $pst -Destination $validationPst -Force

$outlook = $null
$namespace = $null
$store = $null
$root = $null
$attached = $false
$errors = New-Object System.Collections.Generic.List[string]
$subjects = New-Object System.Collections.Generic.List[string]
$folderNames = New-Object System.Collections.Generic.List[string]
$folderCount = 0
$messageCount = 0
$attachmentCount = 0
$outlookVersion = $null
$rootName = $null

try {
    try {
        $outlook = New-Object -ComObject Outlook.Application
        $outlookVersion = [string]$outlook.Version
        $namespace = $outlook.GetNamespace("MAPI")

        # OlStoreType.olStoreUnicode = 2.
        $namespace.AddStoreEx($validationPst, 2)
        $attached = $true

        Start-Sleep -Milliseconds 500
        $store = Find-StoreByPath -Namespace $namespace -TargetPath $validationPst
        if ($null -eq $store) {
            throw "Outlook mounted the PST but the matching Store could not be found."
        }

        if (-not $store.IsOpen) {
            throw "Outlook Store exists but is not open."
        }

        $root = $store.GetRootFolder()
        $rootName = [string]$root.Name

        Walk-Folder -Folder $root -FolderCount ([ref]$folderCount) -MessageCount ([ref]$messageCount) -AttachmentCount ([ref]$attachmentCount) -Subjects $subjects -FolderNames $folderNames

        if ($rootName -ne [string]$expected.root_name) {
            $errors.Add("root_name expected '$($expected.root_name)' but got '$rootName'")
        }
        if ($folderCount -ne [int]$expected.folder_count) {
            $errors.Add("folder_count expected $($expected.folder_count) but got $folderCount")
        }
        if ($messageCount -ne [int]$expected.message_count) {
            $errors.Add("message_count expected $($expected.message_count) but got $messageCount")
        }
        if ($attachmentCount -ne [int]$expected.attachment_count) {
            $errors.Add("attachment_count expected $($expected.attachment_count) but got $attachmentCount")
        }

        foreach ($subject in $expected.subjects) {
            if (-not $subjects.Contains([string]$subject)) {
                $errors.Add("missing subject '$subject'")
            }
        }

        foreach ($folderName in $expected.required_folders) {
            if (-not $folderNames.Contains([string]$folderName)) {
                $errors.Add("missing folder '$folderName'")
            }
        }
    }
    catch {
        $errors.Add($_.Exception.Message)
    }
}
finally {
    if ($attached -and $null -ne $namespace -and $null -ne $root) {
        try {
            $namespace.RemoveStore($root)
        }
        catch {
            $errors.Add("RemoveStore failed: $($_.Exception.Message)")
        }
    }

    Release-ComObject $root
    Release-ComObject $store
    Release-ComObject $namespace

    if ($null -ne $outlook) {
        try {
            $outlook.Quit()
        }
        catch {
        }
    }
    Release-ComObject $outlook

    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$report = [ordered]@{
    validator = "outlook-com"
    status = $(if ($errors.Count -eq 0) { "ok" } else { "failed" })
    input_pst = $pst
    validation_copy = $validationPst
    outlook_version = $outlookVersion
    root_name = $rootName
    folder_count = $folderCount
    message_count = $messageCount
    attachment_count = $attachmentCount
    subjects = @($subjects)
    folders = @($folderNames)
    errors = @($errors)
}

$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportFullPath -Encoding UTF8

if ($errors.Count -ne 0) {
    foreach ($errorMessage in $errors) {
        Write-Error $errorMessage
    }
    exit 1
}

Write-Host "Outlook interoperability validation passed."
Write-Host "Folders: $folderCount; messages: $messageCount; attachments: $attachmentCount"
exit 0
