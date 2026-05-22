# Desktop Pet Agent — Sumi

桌面宠物精灵 Sumi —— Claude Code 的可视化伴侣。定时提醒、AI 主动关怀、权限一键审批、聊天对话，全都从一只桌宠的气泡里完成。

基于 pywebview (WebView2) + Claude Code，**零重量级依赖**（不依赖 langchain / pydantic / PySide6）。

## 快速安装

### PowerShell 一键安装

```powershell
irm https://raw.githubusercontent.com/laijliang/desktop-pet-agent/main/install.ps1 | iex
```

自动完成：检查 Python → 创建虚拟环境 → 安装依赖 → 注册 Claude Code 插件 → 创建桌面快捷方式。

### 手动安装

```powershell
git clone https://github.com/laijliang/desktop-pet-agent.git
cd desktop-pet-agent
pip install -e .
```

安装完成后，终端输入 `pet` 启动，或下次 Claude Code 启动时自动出现。

### 便携版 .exe（无需 Python）

从 [GitHub Releases](https://github.com/laijliang/desktop-pet-agent/releases) 下载 `DesktopPetAgent-v*.7z`，解压后双击运行。约 15-25 MB（不再捆绑 PySide6，改用系统自带的 WebView2 渲染）。

## 前置要求

- **Claude Code** — 聊天与智能提醒功能基于 Claude Code CLI，支持 Claude 订阅版或 Anthropic API Key
- **Tavily API Key（可选）** — 用于联网搜索功能，在 `~/.desktop-pet-agent.env` 中配置：

```env
# 可选 — 联网搜索
TAVILY_API_KEY=tvly-你的key
```

## 功能

### 提醒事项
- 右键 → "添加提醒" 设置本地定时提醒，到时间弹出气泡
- **智能提醒**：AI 定期分析待办列表，主动判断是否需要提醒你
- 气泡按钮：知道了 / 稍后提醒 / 打开聊天

### 权限审批（新）
- Claude Code 请求工具权限时，宠物弹出权限气泡
- 三个按钮：**始终允许** / **允许本次** / **拒绝**
- 不用切到 Claude Code 窗口就能批准权限

### 聊天对话
- 双击宠物或右键 → "打开聊天"
- 支持短期记忆（SQLite 持久化），重启后仍可回忆
- 支持 Tavily 联网搜索

### 个性化
- 拖拽移动位置，自动记忆坐标
- 右键 → 设置：图标大小、Tavily API Key、切换宠物皮肤
- 系统托盘常驻

## 环境要求

- Python 3.12+（仅 pip 安装需要）
- 便携版 .exe 无需任何环境，直接双击

## 项目结构

```text
desktop-pet-agent/
├── main.py                          # 开发入口
├── pyproject.toml                   # 包配置（轻量依赖：pywebview + pystray）
├── build.spec                       # PyInstaller 打包
├── install.ps1                      # PowerShell 一键安装
├── scripts/
│   ├── run.bat                      # 开发快捷启动
│   └── pet.bat                      # 最小化静默启动
├── .github/workflows/release.yml    # CI/CD 自动构建发布
├── .claude-plugin/manifest.json     # Claude Code 插件声明
├── hooks/
│   ├── on_session_start.py          # 随 Claude Code 自启
│   └── permission_request.py        # 权限请求转发
├── skills/pet.md                    # Claude Code 技能定义
├── desktop_pet_mcp/                 # MCP 服务器（提醒 CRUD + 搜索）
├── Idle (32x32)_frames/             # 精灵图素材
└── src/desktop_pet_agent/
    ├── app_webview.py               # 主控（WebView 窗口管理）
    ├── pet_window.py                # 原生 Win32 透明宠物窗口 + 气泡
    ├── _win32_transparency.py       # Win32 透明窗口底层
    ├── ui_webview/                  # Web 前端资源
    │   ├── pet.html / pet.css / pet.js       # 宠物精灵 + 右键菜单
    │   ├── chat.html / chat.css / chat.js    # 聊天界面
    │   └── settings.html / settings.css / settings.js  # 设置面板
    ├── config.py                    # 配置读写（dataclass）
    ├── models.py                    # 数据模型（dataclass）
    ├── proactive.py                 # AI 智能提醒（调 Claude Code CLI）
    ├── permission_server.py         # 权限 IPC 服务器
    ├── reminder_store.py            # 提醒增删改查
    ├── pet_loader.py                # 宠物皮肤发现与加载（PIL 帧切片）
    ├── workers.py                   # 后台线程（原生 threading，无 Qt 依赖）
    └── ...
```

## 技术架构

```text
用户操作 → PetWindow (原生 Win32 透明窗口)
              │  ├─ HTML/CSS/JS (pywebview / WebView2 渲染)
              │  ├─ 拖拽移动、精灵动画、右键菜单
              │  └─ 气泡：提醒 / 权限审批
              │
              ├─ 提醒 → ReminderStore (JSON)
              │         └─ 定时弹出气泡
              │
              ├─ 智能提醒 → proactive.py
              │              └─ subprocess → Claude Code CLI
              │
              ├─ 权限审批 → Claude Code PermissionRequest Hook
              │              └─ HTTP → PermissionServer
              │                        └─ 权限气泡（用户点击）
              │
              └─ MCP 桥接 → desktop_pet_mcp (stdio JSON-RPC)
                             ├─ create_reminder / list_reminders
                             └─ web_search (Tavily)
```

### 为什么从 PySide6 换成 pywebview？

| 对比项 | PySide6（旧） | pywebview（新） |
| --- | --- | --- |
| 安装包大小 | ~200 MB | ~3 MB |
| 打包后 .exe | 80-110 MB | 15-25 MB |
| 渲染引擎 | Qt WebEngine（捆绑 Chromium） | WebView2（Windows 11 自带） |
| UI 开发 | Qt 控件 + QML | HTML / CSS / JS |
| 透明窗口 | 复杂黑魔法 | Win32 API 直接控制 |
| 启动速度 | 较慢（加载 Qt 运行时） | 快（复用系统 WebView2） |

核心思路：Windows 10/11 都预装了 WebView2 运行时，不再需要每个应用捆绑一个完整的 Chromium。界面用 Web 技术写也更灵活，气泡、动画、样式都可以直接用 CSS 搞定。
