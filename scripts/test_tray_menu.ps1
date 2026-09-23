# Tray menu automated verification (ASCII only).
# Expand overflow flyout -> locate Pelica icon -> simulate right click -> read popup menu.
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Mouse {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
    public static void RightClick(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(200);
        mouse_event(0x0008, 0, 0, 0, UIntPtr.Zero);
        mouse_event(0x0010, 0, 0, 0, UIntPtr.Zero);
    }
    public static void LeftClick(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(200);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
    }
}
"@

function Find-ButtonByName($root, $needle) {
    $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($el in $all) {
        if ($el.Current.Name -like "*$needle*") { return $el }
    }
    return $null
}

$root = [System.Windows.Automation.AutomationElement]::RootElement

$taskbar = $root.FindFirst([System.Windows.Automation.TreeScope]::Children,
    (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty, "Shell_TrayWnd")))
if (-not $taskbar) { Write-Output "NO-TASKBAR"; exit 1 }

$chevron = $null
$tbAll = $taskbar.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
# Win11 chevron Chinese name built from code points (avoid .ps1 encoding issues)
$cnName = [string][char]0x663E + [char]0x793A + [char]0x9690 + [char]0x85CF + [char]0x7684 + [char]0x56FE + [char]0x6807
foreach ($el in $tbAll) {
    $n = $el.Current.Name
    if ($n -match "hidden|Shows|chevron" -or $n -eq $cnName) { $chevron = $el; break }
}
if (-not $chevron) {
    # fall back: small button elements, pick the right-most one in the tray area
    $bestX = -1
    foreach ($el in $tbAll) {
        $cn = $el.Current.ClassName
        $r = $el.Current.BoundingRectangle
        if ($r.Width -gt 0 -and $r.Width -lt 60 -and $r.Height -gt 0 -and $r.Height -lt 60 `
                -and $cn -match "Button|Icon") {
            if ($r.X -gt $bestX) { $bestX = $r.X; $chevron = $el }
        }
    }
}
if (-not $chevron) { Write-Output "NO-CHEVRON"; exit 1 }
$cr = $chevron.Current.BoundingRectangle
[Mouse]::LeftClick([int]($cr.X + $cr.Width / 2), [int]($cr.Y + $cr.Height / 2))
Start-Sleep -Milliseconds 1500

$overflow = $root.FindFirst([System.Windows.Automation.TreeScope]::Children,
    (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty, "NotifyIconOverflowWindow")))
if (-not $overflow) { Write-Output "NO-OVERFLOW-WINDOW"; exit 1 }
$btn = Find-ButtonByName $overflow "Pelica"
if (-not $btn) { Write-Output "NO-PELICA-BUTTON"; exit 1 }
$br = $btn.Current.BoundingRectangle
Write-Output ("ICON-RECT {0},{1}" -f [int]$br.X, [int]$br.Y)

[Mouse]::RightClick([int]($br.X + $br.Width / 2), [int]($br.Y + $br.Height / 2))
Start-Sleep -Milliseconds 1800

$menu = $root.FindFirst([System.Windows.Automation.TreeScope]::Children,
    (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty, "#32768")))
if (-not $menu) { Write-Output "NO-MENU-SHOWN"; exit 1 }
$mAll = $menu.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
Write-Output "MENU-ITEMS:"
foreach ($el in $mAll) {
    $n = $el.Current.Name
    if ($n) { Write-Output ("  - " + $n) }
}
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{ESC}")
