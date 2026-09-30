---
description: 列出所有可用的 Superpowers Skills 及其用途说明
---

# Superpowers Skills 总览

你当前安装了以下 skills，它们会自动被我（AI）在适当时机调用：

## 工作流类

| Skill | 用途 |
|-------|------|
| `/brainstorming` | 创意/新功能前的需求探索和设计 |
| `/plan` | 将任务分解为小步骤，制定实现计划 |
| `/executing-plans` | 按已写好的计划在独立会话中执行 |
| `/verification-before-completion` | 完成/修复前运行验证，确认无误再断言 |
| `/finishing-a-development-branch` | 功能完成后决定合并、提 PR 或清理 |

## 开发实践类

| Skill | 用途 |
|-------|------|
| `/test-driven-development` | 测试驱动开发：先写测试，再实现，再重构 |
| `/systematic-debugging` | 遇到 bug/测试失败时，系统性地定位根因 |
| `/code-review` | 代码审查：正确性、可读性、架构、安全、性能 |
| `/requesting-code-review` | 完成任务/合并前请求审查 |
| `/receiving-code-review` | 收到审查反馈后的处理 |

## 协作与并行类

| Skill | 用途 |
|-------|------|
| `/dispatching-parallel-agents` | 2 个以上独立任务并行处理 |
| `/subagent-driven-development` | 用子代理执行实现计划 |
| `/using-git-worktrees` | 用 git worktree 隔离工作空间 |

## 元技能类

| Skill | 用途 |
|-------|------|
| `/writing-skills` | 创建或编辑新的 skill 文件 |
| `/writing-plans` | 为多步骤任务编写实现计划 |
| `/using-superpowers` | （就是这个）如何发现和使用所有 skills |

---

💡 这些 skills 不需要你手动输入——当任务匹配时，我会自动调用对应的 skill。你也可以随时说"用 brainstorming 方式做"来强制指定某个 skill。
