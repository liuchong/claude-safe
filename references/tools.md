# 工具适配

## 加载完整 Skill

1. 将整个目录复制或链接到需要使用的工具的 Skill 目录；scripts、references、examples 和 assets 必须一起存在。
2. 当前工具有原生技能选择时显式选 claude-safe；没有时让它先读 SKILL.md，再按分支读取本仓其他文件，不需要其他知识库或私人 Skill。
3. 工具具有只读能力时只能检查和说明；能写文件、执行命令及访问目标电脑时才能实际配置。系统、支付和账号授权仍由现有宿主机制控制。

| 工具 | 常用用户目录 | 显式使用 |
| --- | --- | --- |
| Codex | ~/.agents/skills/claude-safe 或 ~/.codex/skills/claude-safe | $claude-safe |
| Cursor | ~/.cursor/skills/claude-safe | 在 Agent 技能选择中选用，或要求读取本目录 |
| Claude Code | ~/.claude/skills/claude-safe | /claude-safe |
| OpenCode | ~/.config/opencode/skills/claude-safe | 加载 claude-safe |
| Antigravity | 使用当前版本原生 Skill 目录 | 原生列表确认发现，或显式读取本目录 |
| 其他有终端能力的 AI | 使用其原生目录或显式读取 | 按同一 SKILL.md 执行 |

## 运行能力

| 对象 | 本仓提供 | 必须在现场验证 |
| --- | --- | --- |
| macOS/Linux | Python 标准库检查、探测、配置生成、精确写入/回滚，部署命令和客户端步骤 | 实际系统版本、权限、服务、网络和账户 |
| Windows | 检查/散列/探测及原生配置操作说明 | ACL、驱动和客户端；POSIX文件事务不适用 |
| Ubuntu VPS | 购买、SSH、软件、密钥、接口、NAT、防火墙、验收与取消步骤 | 购买、真实UDP、重启与出口 |
| 手机 | SIM/eSIM与客户端操作顺序 | 设备兼容、本人验证、实际短信、费用 |
| 纯文字聊天 | 可说明手册 | 没有目标执行能力不能声称完成配置 |

- dependencies: 软件包和供应商服务在实际操作时使用，本仓的操作知识不依赖外部文章、引用或其他 Skill；本仓不包含操作系统、VPN内核和商业服务的完整发行包。
- no_fork: 不创建隐藏 AI worker 或子智能体，不为格式兼容切换当前模型，不以无人值守为由取消宿主权限边界。
