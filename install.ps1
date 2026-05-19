<#
.SYNOPSIS
    Desktop Pet Agent 一键安装脚本
.DESCRIPTION
    自动检查环境、创建虚拟环境、安装依赖、注册 Claude Code 插件。
.PARAMETER DevMode
    开发模式：从 GitHub 克隆源码安装（需要 Git）。
    不加此参数则从 PyPI 安装。
.PARAMETER Branch
    Git 分支名（仅 DevMode），默认 "main"。
.PARAMETER InstallDir
    安装目录，默认 "$env:LOCALAPPDATA\DesktopPetAgent"。
.EXAMPLE
    # 一键安装（PyPI）
    irm https://raw.githubusercontent.com/laijliang/desktop-pet-agent/main/install.ps1 | iex

.EXAMPLE
    # 开发模式安装
    .\install.ps1 -DevMode
#>

param(
    [switch]$DevMode,
    [string]$Branch = "main",
    [string]$InstallDir = "$env:LOCALAPPDATA\DesktopPetAgent"
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/laijliang/desktop-pet-agent.git"

Write-Host "`n=== Desktop Pet Agent 安装程序 ===`n" -ForegroundColor Cyan

# ── 1. 检查 Python ──
Write-Host "[1/5] 检查 Python 3.12+ ..." -ForegroundColor Yellow
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    $ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $major, $minor = $ver.Split(".") | ForEach-Object { [int]$_ }
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 12)) {
        Write-Host "错误: 需要 Python 3.12+，当前版本: $ver" -ForegroundColor Red
        Write-Host "请从 https://www.python.org/downloads/ 安装 Python 3.12+"
        exit 1
    }
    Write-Host "  Python $ver ($python)" -ForegroundColor Green
} catch {
    Write-Host "错误: 未找到 Python。请先安装 Python 3.12+" -ForegroundColor Red
    exit 1
}

# ── 2. 获取源码 ──
Write-Host "[2/5] 获取源码 ..." -ForegroundColor Yellow
if ($DevMode) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Host "错误: DevMode 需要 Git。请从 https://git-scm.com/ 安装 Git" -ForegroundColor Red
        exit 1
    }
    if (Test-Path $InstallDir) {
        Write-Host "  目录已存在，执行 git pull ..."
        Push-Location $InstallDir
        git checkout $Branch
        git pull origin $Branch
        Pop-Location
    } else {
        Write-Host "  git clone $RepoUrl ..."
        git clone -b $Branch $RepoUrl $InstallDir
    }
} else {
    # 非 DevMode：创建轻量目录，直接用 pip 安装
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
}

# ── 3. 创建虚拟环境 ──
Write-Host "[3/5] 创建虚拟环境 ..." -ForegroundColor Yellow
$VenvDir = "$InstallDir\.venv"
if (-not (Test-Path $VenvDir)) {
    & python -m venv $VenvDir
}
$pip = "$VenvDir\Scripts\python.exe -m pip"

# ── 4. 安装依赖 ──
Write-Host "[4/5] 安装依赖 ..." -ForegroundColor Yellow
if ($DevMode) {
    Invoke-Expression "& $pip install -e `"$InstallDir`" --quiet"
} else {
    Invoke-Expression "& $pip install desktop-pet-agent --quiet"
}
Write-Host "  依赖安装完成" -ForegroundColor Green

# ── 5. 注册 Claude Code 插件 ──
Write-Host "[5/5] 注册 Claude Code 插件 ..." -ForegroundColor Yellow
$ClaudePluginDir = "$env:USERPROFILE\.claude\plugins\desktop-pet"
New-Item -ItemType Directory -Force -Path $ClaudePluginDir | Out-Null

# 复制插件的 manifest 和 hooks
$PluginSource = if ($DevMode) { $InstallDir } else { "$VenvDir\Lib\site-packages\desktop_pet_agent" }
# The plugin files live in the repo root, not in the package
if ($DevMode) {
    Copy-Item "$InstallDir\.claude-plugin\*" $ClaudePluginDir -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item "$InstallDir\hooks\*" $ClaudePluginDir -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item "$InstallDir\skills\*" $ClaudePluginDir -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item "$InstallDir\desktop_pet_mcp\*" $ClaudePluginDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "  插件已注册到 $ClaudePluginDir" -ForegroundColor Green

# ── 完成 ──
Write-Host "`n=== 安装完成！===`n" -ForegroundColor Cyan
Write-Host "启动方式:" -ForegroundColor White
Write-Host "  宠物 GUI:  & `"$VenvDir\Scripts\python.exe`" -m desktop_pet_agent.app" -ForegroundColor Gray
Write-Host "  或直接:   & `"$VenvDir\Scripts\pet.exe`"" -ForegroundColor Gray
Write-Host "`n下次 Claude Code 启动时宠物会自动出现。" -ForegroundColor White

# 创建桌面快捷方式
$Desktop = [Environment]::GetFolderPath("Desktop")
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut("$Desktop\DesktopPetAgent.lnk")
$Shortcut.TargetPath = "$VenvDir\Scripts\python.exe"
$Shortcut.Arguments = "-m desktop_pet_agent.app"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "桌面宠物精灵 Sumi"
$Shortcut.Save()
Write-Host "已创建桌面快捷方式" -ForegroundColor Green
