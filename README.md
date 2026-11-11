# Claude Safe

一个仓库、一个 Skill：由 AI 连续完成 Claude 环境的准备、配置和验收。包含电脑整理、固定出口、VPS 购买与 VPN 部署、客户端分流、DNS、浏览器、手机号、账号和支付的具体操作步骤，以及配置生成、精确写入和回滚工具。

## 使用

把完整目录安装到执行工具的用户 Skill 目录，或让有终端和文件权限的 AI 读取本目录：

```text
使用 claude-safe，配置当前电脑的 Claude 环境。
先检查已有线路、客户端和账号，能复用就复用。
按操作手册连续完成配置和实际验收，不只给方案。
把必须由本人完成的支付、验证码和系统授权集中告诉我。
购买前沿用我已给出的预算；没有预算先完成不花钱的部分。
```

只检查时说“使用 claude-safe，只检查、不修改”。安装整个目录，不能只复制 SKILL.md。

| 内容 | 入口 |
| --- | --- |
| 执行顺序和完成标准 | [SKILL.md](SKILL.md) |
| 软件安装与旧设置整理 | [软件操作手册](references/software.md) |
| 电脑准备、输入、备份、恢复 | [配置流程](references/configuration.md) |
| 购买 VPS、固定 IP、部署 WireGuard | [服务器操作手册](references/server.md) |
| 客户端、分流、DNS、浏览器与断线检查 | [本机操作手册](references/adapters.md) |
| 邮箱、手机、账号、支付与续费 | [账号操作手册](references/accounts.md) |
| 逐项验收和交付 | [验收表](references/acceptance.md) |
| 各 AI 工具的加载和执行能力 | [工具适配](references/tools.md) |

## 可执行工具

需要 Python 3.9+；HTTPS 探测另需 curl，服务器部署需目标机具备 SSH、管理员权限和 WireGuard 工具。生成器不购买资源、不连接服务器、不修改主机网络。

```sh
python3 -B scripts/claude_safe.py inspect
python3 -B scripts/claude_safe.py hash '<目标配置>'
python3 -B scripts/claude_safe.py apply-files --plan '<精确文件计划>' --state-dir '<私密恢复目录>'
python3 -B scripts/claude_safe.py rollback --state-dir '<同一恢复目录>' --transaction '<事务ID>'
python3 -B scripts/network_plan.py --input '<私密参数.json>' --side client --output-dir '<新的私密输出目录>'
```

network_plan.py 确定性生成服务端接口配置、Mihomo 节点、固定策略和域名规则。私钥只读自本机受限文件，标准输出仅报告文件数量和状态，不覆盖已有输出目录。文件事务工具检查全部旧散列后才修改，保留恢复材料，遇并发修改拒绝覆盖。

macOS/Linux 支持精确文件事务；Windows 的文件事务尚无经验证的 ACL 适配，AI 应使用系统原生方式。登录、KYC、短信验证码、付款二次认证及系统受保护确认仍由本人在实际表单完成。环境配置不能改变服务地区资格，也不保证账号永不受限。

## 开发验证

```sh
python3 -B -m unittest discover -s tests -v
```

测试使用隔离的合成文件及模拟命令，不付款、不购买服务器、不改变真实网络。真实服务器、手机客户端及各系统的最终验收需要在对应目标执行；生成配置成功不能冒充部署成功。

MIT License。
