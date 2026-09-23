# 读取 Pelica Console 运行窗口的实际 UI 内容（UI Automation，只读）
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, "Pelica Console")
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output "WINDOW-NOT-FOUND"; exit 1 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
$texts = @()
foreach ($el in $all) {
    $t = $el.Current.Name
    if ($t -and $t.Length -gt 1 -and $t.Length -lt 120) { $texts += $t }
}
$texts | Select-Object -First 30
