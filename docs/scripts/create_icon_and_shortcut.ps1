<#
.SYNOPSIS
    Generates OpenChromLab.ico and OpenChromLab.lnk Windows shortcut for OpenChromLab.
#>

param(
    [string]$WorkspaceRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $WorkspaceRoot) {
    # Default to parent directory of scripts folder
    $WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

Write-Output "Workspace root: $WorkspaceRoot"

Add-Type -AssemblyName System.Drawing

$icoPath = Join-Path $WorkspaceRoot "OpenChromLab.ico"
$batPath = Join-Path $WorkspaceRoot "OpenChromLab.bat"
$lnkPath = Join-Path $WorkspaceRoot "OpenChromLab.lnk"

# -------------------------------------------------------------------------
# 1. Generate OpenChromLab.ico
# -------------------------------------------------------------------------
Write-Output "Generating $icoPath..."

$size = 48
$bmp = New-Object System.Drawing.Bitmap $size, $size
$g = [System.Drawing.Graphics]::FromImage($bmp)

$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

# Background: Deep Navy (#1F3864) with subtle rounded corner appearance
$bgBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(31, 56, 100))
$g.FillRectangle($bgBrush, 0, 0, $size, $size)
$bgBrush.Dispose()

# Subtle outer border (#2F4E85)
$borderPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(47, 78, 133), 1.0)
$g.DrawRectangle($borderPen, 0, 0, $size - 1, $size - 1)
$borderPen.Dispose()

# Subtle reference grid lines (#263E66)
$gridPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(38, 62, 102), 1.0)
$g.DrawLine($gridPen, 4, 15, 44, 15)
$g.DrawLine($gridPen, 4, 26, 44, 26)
$g.DrawLine($gridPen, 15, 6, 15, 40)
$g.DrawLine($gridPen, 32, 6, 32, 40)
$gridPen.Dispose()

# Baseline at y = 38 (#CBD5E1)
$basePen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(203, 213, 225), 1.6)
$g.DrawLine($basePen, 4, 38, 44, 38)
$basePen.Dispose()

# Peak 1 Shading (FID peak - Cyan semi-transparent)
$peak1FillBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush (
    (New-Object System.Drawing.PointF 17, 10),
    (New-Object System.Drawing.PointF 17, 38),
    [System.Drawing.Color]::FromArgb(160, 0, 210, 255),
    [System.Drawing.Color]::FromArgb(30, 0, 100, 180)
)
$p1FillPts = @(
    (New-Object System.Drawing.PointF 6, 38),
    (New-Object System.Drawing.PointF 10, 37),
    (New-Object System.Drawing.PointF 13, 25),
    (New-Object System.Drawing.PointF 17, 10),
    (New-Object System.Drawing.PointF 21, 25),
    (New-Object System.Drawing.PointF 24, 36),
    (New-Object System.Drawing.PointF 26, 38)
)
$g.FillClosedCurve($peak1FillBrush, $p1FillPts, [System.Drawing.Drawing2D.FillMode]::Winding, 0.4)
$peak1FillBrush.Dispose()

# Peak 2 Shading (Split Peak - Golden Amber semi-transparent)
$peak2FillBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush (
    (New-Object System.Drawing.PointF 33, 17),
    (New-Object System.Drawing.PointF 33, 38),
    [System.Drawing.Color]::FromArgb(160, 255, 215, 0),
    [System.Drawing.Color]::FromArgb(30, 180, 120, 0)
)
$p2FillPts = @(
    (New-Object System.Drawing.PointF 26, 38),
    (New-Object System.Drawing.PointF 29, 34),
    (New-Object System.Drawing.PointF 33, 17),
    (New-Object System.Drawing.PointF 37, 30),
    (New-Object System.Drawing.PointF 40, 36),
    (New-Object System.Drawing.PointF 42, 38)
)
$g.FillClosedCurve($peak2FillBrush, $p2FillPts, [System.Drawing.Drawing2D.FillMode]::Winding, 0.4)
$peak2FillBrush.Dispose()

# Peak 1 Curve (Cyan #00D2FF, width 2.2)
$curve1Pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(0, 210, 255), 2.2)
$curve1Pts = @(
    (New-Object System.Drawing.PointF 5, 38),
    (New-Object System.Drawing.PointF 10, 37),
    (New-Object System.Drawing.PointF 13, 25),
    (New-Object System.Drawing.PointF 17, 10),
    (New-Object System.Drawing.PointF 21, 25),
    (New-Object System.Drawing.PointF 24, 36),
    (New-Object System.Drawing.PointF 26, 38)
)
$g.DrawCurve($curve1Pen, $curve1Pts, 0.4)
$curve1Pen.Dispose()

# Peak 2 Curve (Gold #FFD700, width 2.0)
$curve2Pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(255, 215, 0), 2.0)
$curve2Pts = @(
    (New-Object System.Drawing.PointF 26, 38),
    (New-Object System.Drawing.PointF 29, 34),
    (New-Object System.Drawing.PointF 33, 17),
    (New-Object System.Drawing.PointF 37, 30),
    (New-Object System.Drawing.PointF 40, 36),
    (New-Object System.Drawing.PointF 43, 38)
)
$g.DrawCurve($curve2Pen, $curve2Pts, 0.4)
$curve2Pen.Dispose()

# Peak Apex Markers (Magenta #FF007F dots)
$apexBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 0, 127))
$g.FillEllipse($apexBrush, 15.5, 8.5, 3.0, 3.0)
$g.FillEllipse($apexBrush, 31.5, 15.5, 3.0, 3.0)
$apexBrush.Dispose()

# Baseline Anchor Handles (White / Gold dots with #D83B01 outline)
$ancOutlinePen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(216, 59, 1), 1.2)
$whiteBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
$goldBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 215, 0))

# Left Anchor
$g.FillEllipse($whiteBrush, 4.0, 36.5, 3.5, 3.5)
$g.DrawEllipse($ancOutlinePen, 4.0, 36.5, 3.5, 3.5)

# Valley / Split Anchor
$g.FillEllipse($goldBrush, 24.5, 36.5, 3.5, 3.5)
$g.DrawEllipse($ancOutlinePen, 24.5, 36.5, 3.5, 3.5)

# Right Anchor
$g.FillEllipse($whiteBrush, 41.0, 36.5, 3.5, 3.5)
$g.DrawEllipse($ancOutlinePen, 41.0, 36.5, 3.5, 3.5)

$ancOutlinePen.Dispose()
$whiteBrush.Dispose()
$goldBrush.Dispose()
$g.Dispose()

# Save ICO
$hicon = $bmp.GetHicon()
$ico = [System.Drawing.Icon]::FromHandle($hicon)
$fs = New-Object System.IO.FileStream $icoPath, ([System.IO.FileMode]::Create)
$ico.Save($fs)
$fs.Close()
$ico.Dispose()
$bmp.Dispose()

Write-Output "Successfully created $icoPath"

# -------------------------------------------------------------------------
# 2. Generate OpenChromLab.lnk Windows Shortcut
# -------------------------------------------------------------------------
Write-Output "Generating $lnkPath..."

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($lnkPath)
$sc.TargetPath = $batPath
$sc.WorkingDirectory = $WorkspaceRoot
$sc.IconLocation = "$icoPath,0"
$sc.Description = "OpenChromLab - Open-Source Chromatography Data System"
$sc.Save()

Write-Output "Successfully created $lnkPath"
