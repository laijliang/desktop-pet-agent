# Desktop Pet Agent — Sumi

桌面宠物精灵 Sumi —— Claude Code 的可视化伴侣。定时提醒、AI 主动关怀、权限一键审批、聊天对话，全都从一只桌宠的气泡里完成。

基于 PySide6 + DeepSeek，**零重量级依赖**（不依赖 langchain / pydantic）。

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

从 [GitHub Releases](https://github.com/laijliang/desktop-pet-agent/releases) 下载 `DesktopPetAgent-v*.7z`，解压后双击运行。约 80-110 MB。

## 配置 API Key

在用户目录创建 `.desktop-pet-agent.env`：

```env
# 必需 — DeepSeek API Key
DEEPSEEK_API_KEY=sk-你的key

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
- 右键 → 设置：图标大小、API Key、切换宠物皮肤
- 系统托盘常驻

## 环境要求

- Python 3.12+（仅 pip 安装需要）
- 便携版 .exe 无需任何环境，直接双击

## 项目结构

```text
desktop-pet-agent/
├── main.py                          # 开发入口
├── pyproject.toml                   # 包配置（零重量级依赖）
├── build.spec                       # PyInstaller 打包
├── install.ps1                      # PowerShell 一键安装
├── .github/workflows/release.yml    # CI/CD 自动构建发布
├── .claude-plugin/manifest.json     # Claude Code 插件声明
├── hooks/
│   ├── on_session_start.py          # 随 Claude Code 自启
│   └── permission_request.py        # 权限请求转发
├── skills/pet.md                    # Claude Code 技能定义
├── desktop_pet_mcp/                 # MCP 服务器（提醒 CRUD + 搜索）
├── Idle (32x32)_frames/             # 精灵图素材
└── src/desktop_pet_agent/
    ├── app.py                       # 主控
    ├── ui.py                        # 全部 UI：宠物、气泡、权限气泡、聊天、设置
    ├── config.py                    # 配置读写（dataclass）
    ├── models.py                    # 数据模型（dataclass）
    ├── proactive.py                 # AI 智能提醒（直接调 DeepSeek API）
    ├── permission_server.py         # 权限 IPC 服务器
    ├── reminder_store.py            # 提醒增删改查
    ├── pet_loader.py                # 宠物皮肤发现与加载
    └── ...
```

## 技术架构

```text
用户操作 → PetWindow / ChatWindow
              │
              ├─ 提醒 → ReminderStore (JSON)
              │         └─ BubbleWindow（定时弹出）
              │
              ├─ 智能提醒 → proactive.py
              │              └─ urllib POST → DeepSeek API
              │
              ├─ 权限审批 → Claude Code PermissionRequest Hook
              │              └─ HTTP → PermissionServer
              │                        └─ PermissionBubble（用户点击）
              │
              └─ MCP 桥接 → desktop_pet_mcp (stdio JSON-RPC)
                             ├─ create_reminder / list_reminders
                             └─ web_search (Tavily)
```
