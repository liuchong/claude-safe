# VPS 购买、固定出口与 VPN 部署

## 1. 确定购买对象

1. 先查是否已有本人控制且获准使用的节点或 VPS；有就复用。网站虚拟主机、共享 PHP 空间不能安装内核 VPN，不购买这种产品；选择有 root/sudo、SSH、UDP、公网 IPv4 的 Linux 虚拟机。
2. 用户需要美国出口时，只选择美国机房；默认候选纽约或旧金山，按当前可用性和到用户的实测延迟选择，不自动改到其他国家。数据中心 IP 不等于住宅 IP，独享服务器也不自动变成住宅线路，不作这类承诺。
3. 默认单台、Ubuntu 24.04 LTS、x86_64、至少 1 vCPU、1 GiB RAM、普通 SSD、公网 IPv4；只跑个人隧道，不装控制面板、网站、API 中转、容器集群或数据库。套餐不支持这些条件时先重新比较，不擅自扩预算。
4. 计算月费、税、IPv4、流量包及超额、备份、快照、存储和自动续费。将首次及持续费用与用户已授权上限比较；零预算不能下单。关机通常仍计费，删除实例与释放附加资源才结束相应账单。
5. 固定出口默认使用存续期间保持不变的独立公网 IPv4；需要销毁重建后也保留同一地址时，明确加购或分配可保留地址，并单独核对绑定、闲置费用与删除策略。不把动态共享出口称作固定地址。

## 2. 注册与支付

1. 使用用户指定的供应商；未指定时，在有授权预算的前提下优先选择支持 SSH 公钥、实例查询和费用可见的供应商。下文给出 DigitalOcean 的固定执行分支，不要求另读教程。
2. 从浏览器地址栏进入供应商官方控制台，核对服务名称和域名，选择注册。使用本人长期控制的邮箱，设置密码管理器生成的独立密码，完成邮件确认；不得使用接码平台注册或购买他人账号。
3. 开启 MFA，恢复代码保存密码管理器。账单姓名、地址、国家和卡信息使用真实资料；本人在受保护付款页面输入，不发给 AI，不截图。
4. 供应商要求 CAPTCHA、3DS、证件或人工审核时，由本人完成。AI 保留当前步骤并完成其余准备，不伪造资料、绕验证或一遍遍提交支付。
5. 控制台显示账号可用且账单已激活才继续。只有扣款通知但账号待审核时不要再注册或重复付费。

## 3. 创建实例：原生 CLI 分支

1. 优先使用已有 doctl。没有时按 [软件准备](software.md) 安装。运行 `doctl version`、`doctl compute droplet create --help`；若安装版本不支持下列参数，先使用控制台分支，不盲试参数。
2. 复用已有获准的登录 context。缺少时本人在控制台生成只覆盖本次实例管理所需的令牌，由原生 `doctl auth init --context claude-safe` 的受保护输入接收；不可把令牌放参数、聊天或 Git。后续命令显式带 `--context claude-safe`，不更改其他默认登录。
3. 运行以下只读查询，输出仅在私密任务上下文使用，选择仍可用的美国 region、镜像和预算内 size：

```sh
doctl --context claude-safe compute region list --output json
doctl --context claude-safe compute size list --output json
doctl --context claude-safe compute image list-distribution --output json
doctl --context claude-safe compute ssh-key list --output json
doctl --context claude-safe compute droplet list --output json
```

4. SSH 优先复用获准的现有公钥。没有时在私密目录执行 `ssh-keygen -t ed25519 -f '<私密目录>/vps-ssh' -C claude-safe`；使用 SSH Agent 和可恢复的受保护口令。只把 `.pub` 导入供应商，不上传私钥。运行 `doctl --context claude-safe compute ssh-key import claude-safe --public-key-file '<公钥>'`，保存返回的 key ID。
5. 选择唯一实例名，保存本轮请求的名称、地域、size、image、key ID 和预算；先按名称查询是否已存在同一订单的实例，防止重试造成重复收费。把下面参数替换成查询得到的真值：

```sh
doctl --context claude-safe --http-retry-max 0 compute droplet create '<唯一名称>' \
  --region '<美国region>' --size '<预算内size>' --image '<Ubuntu镜像slug>' \
  --ssh-keys '<SSH key ID>' --wait --wait-timeout 5m --output json
```

6. 不附加付费备份、额外卷或软件市场镜像。创建响应超时不代表失败，先查询原名称和资源 ID，不重复 create。状态 active、公网地址可见后才继续；记录实例 ID，避免后续靠模糊名称删除。

## 4. 创建实例：控制台分支

1. 打开“创建虚拟机/Droplet”；选择美国 region、普通共享 CPU、预算内最小合格套餐、Ubuntu 24.04 LTS。
2. 认证选择 SSH key，粘贴本轮公钥；不使用邮件明文 root 密码。名称使用本轮唯一名称，数量固定 1。
3. 逐项取消不需要的备份、托管数据库、额外磁盘和付费监控；确认公网 IPv4 与实际价格。付款页超过预算就停止该分支。
4. 点击创建一次；等待实例列表出现原名称和真实 ID，确认 active，记录公网 IPv4 和机房。界面转圈时先刷新原订单，不再创建第二台。
5. 如需可保留 IP，在网络地址页面分配并绑定到这个实例，查看绑定读回；后续 endpoint 采用绑定后实际地址。不要把旧地址和新地址混用。

## 5. SSH 与新机检查

1. 从供应商控制台的串行/网页控制台读取 SSH 主机公钥指纹，通过第二可信渠道核对。`ssh-keyscan` 只能取得密钥，不能独立证明身份；不要用 `StrictHostKeyChecking=no`。
2. 使用明确的目标地址、用户和 IdentityFile 建立 SSH；连接超时 10 秒。首连核对真实指纹后保存，保留这个管理通道直到部署验收完成。
3. 检查系统版本时，通过系统根变量构造配置路径；下文统一采用此写法，所有命令在目标服务器执行：

```sh
cs_root=$(python3 -c 'import os; print(os.sep)')
cs_etc="${cs_root}etc"
cat "$cs_etc/os-release"
ip -4 route show default
ip -4 address
sudo ss -lntup
sudo iptables -S
sudo iptables -t nat -S
```

4. 确认是本次获准的新机，无已有 VPN 接口 cs0、无占用的 UDP 51820、无重叠的 10.77.0.0/24 本地或远端网段。已有服务/防火墙时保留规则，不能直接启用新机防火墙；必要冲突明确标出并选择新的私有子网。
5. 从默认路由取得真实出口接口，例如 eth0 或 ens3，不抄示例值。需要公网地理核实时，检查供应商 region，再用至少一个独立 IP 地理服务核对；两者不一致先查，不循环购买 IP。

## 6. 安装与生成密钥

1. 在新 Ubuntu 执行 `sudo apt-get update`，再执行 `sudo DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard-tools iptables python3`；安装设 5 分钟截止。失败先看源、锁和网络，不杀其他包管理进程，不执行不明远程一键脚本。
2. 创建服务端私密工作目录和密钥；已存在时不覆盖：

```sh
umask 077
mkdir -p ~/AI/caches/claude-safe/setup
cd ~/AI/caches/claude-safe/setup
test ! -e server.key && wg genkey > server.key
wg pubkey < server.key > server.pub
chmod 600 server.key server.pub
```

3. 客户端在本机私密任务目录同样用 `wg genkey > client.key` 和 `wg pubkey < client.key > client.pub`。每台设备一个密钥对和一个隧道地址；不得给多个设备复用同一个 peer。
4. 仅交换公钥：通过已验证 SSH 把 client.pub 传到服务端，把 server.pub 传回本机。各自私钥留在各自机器，不打印到对话。再次执行 `wg pubkey` 与对应 `.pub` 比较，确认没有拿错配对。
5. 将本项目的 scripts/claude_safe.py、scripts/network_plan.py 和 examples/network.json 通过既有 SSH 复制到服务端私密工作目录；它们属于本轮临时部署材料，不是新的常驻控制程序。

## 7. 渲染并启用接口

1. 两端各自复制 network.json，在受限文件里填写 endpoint、port、真实出口接口、无冲突子网、DNS和各密钥文件位置。服务端只需本地 server.key 和 client.pub；客户端只需本地 client.key 和 server.pub，其余路径占位字段不被对应分支读取。
2. 服务端执行 `python3 -B network_plan.py --input network.json --side server --output-dir rendered-server`；本机从 Skill 目录执行 `python3 -B scripts/network_plan.py --input '<本机参数>' --side client --output-dir '<新的本机输出目录>'`。目录必须不存在；失败不反复覆盖旧恢复资料。
3. 服务端生成 server.conf；本机生成 mihomo-merge.json 和原生 client.conf。接口固定 cs0，服务端只准入这个客户端的 /32，转发和 NAT 仅覆盖该 peer，不改变服务器默认路由。生成结果仍是未部署状态。
4. 新机防火墙先允许现有 SSH 管理来源及实际 SSH 端口，再允许本轮 WireGuard UDP 端口；云防火墙和系统防火墙两处都核对。使用 UFW 时先 `sudo ufw status verbose`，仅在确认没有既有策略且管理规则已就位的新机使用下列步骤：

```sh
sudo ufw allow from '<实际管理来源CIDR>' to any port '<实际SSH端口>' proto tcp
sudo ufw allow 51820/udp
sudo ufw enable
sudo ufw status verbose
```

5. 另开一次 SSH 验证仍可连接；失败立即从保留通道或供应商控制台恢复管理规则。不要开放所有端口，不把后台面板放公网。
6. 将生成文件安装到系统配置目录。先确认目标不存在，存在时精确备份并核散列，不能覆盖其他服务。以下命令仍在服务器执行：

```sh
sudo install -d -m 700 "$cs_etc/wireguard"
sudo install -m 600 rendered-server/server.conf "$cs_etc/wireguard/cs0.conf"
printf '%s\n' 'net.ipv4.ip_forward = 1' | sudo tee "$cs_etc/sysctl.d/90-claude-safe.conf"
sudo sysctl -p "$cs_etc/sysctl.d/90-claude-safe.conf"
sudo systemctl start wg-quick@cs0
sudo systemctl enable wg-quick@cs0
sudo systemctl is-active wg-quick@cs0
```

7. 若此前已经手动启动过 cs0，先在保留 SSH 通道下确认归属，再用 `sudo wg-quick down cs0` 后执行 systemctl start；不要重复创建同名接口和防火墙规则。
8. 生成器使用 iptables 只增删本轮 peer 的三条规则，不 flush 现有表。系统使用额外 FORWARD 过滤链时必须检查实际通行；脚本生成并不能证明其他安全策略已允许。`wg show cs0` 只查看必要字段，不用 `showconf` 打印私钥。

## 8. 连通、持久性与失败分支

1. 本机按本机手册加载节点，对目标发一次受控请求；服务器查 peer 的 latest-handshakes 和 transfer，看到近期握手及收发字节才证明隧道实际有流量。
2. 30 秒内无握手：核对 endpoint、UDP 两层防火墙、端口、密钥配对、peer AllowedIPs。修正明确错误后最多再测一次，不空等。
3. 仍无握手且确认本地网络阻断 UDP：标记此 WireGuard 分支 BLOCKED；复用用户已有、已授权的 TCP/TLS 节点进入客户端配置。不擅自改用未说明的协议、不重复购买不同 VPS 碰运气，不假称 WireGuard 能穿透所有网络。
4. 有握手但无应用流量：查 IPv4 forwarding、实际出口接口、精确 FORWARD/NAT 规则、MTU及 DNS；先小请求，再单独降低 MTU 到 1280 验证，不能一次改很多变量。
5. 验证接口配置与启用状态；只有用户允许重启服务器且控制台可恢复时才做真实重启验收，否则记“自启动已配置，重启未实测”。
6. 退出或回滚时先移除客户端对该节点的使用，再 stop/disable 本轮服务，确认其 PostDown 规则已移除；只恢复本轮写入的 sysctl 文件与原值。删除实例、释放保留 IP、取消付费功能须沿原授权，读回资源列表和账单；关机不等于取消收费。
7. 交付后删除本轮服务端临时安装副本和多余渲染文件，保留系统有效配置、双方各自私钥及必要受限恢复材料。不要删用户 SSH key 或现有服务器业务数据。
