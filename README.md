# S-UI Deployer

S-UI Deployer 是一个面向 VPS/EC2 的 S-UI 自动化部署工具。它把可提交的工具源码、模板和文档，与不可提交的站点配置、日志、备份和密钥材料分开管理，适合从单台机器开始，逐步扩展到多台站点。

当前版本以 Ubuntu/Debian、S-UI v1.4.1、OpenSSH/scp 和 S-UI `/apiv2` 为主要目标。工具支持安装 S-UI、配置面板和订阅 HTTPS、创建 API token、导出配置、生成执行计划、应用 TLS/出站/入站/客户端配置，并在修改远端前自动备份。

## 适用场景

- 已经有一台或多台 VPS/EC2，需要在每台机器上部署一个 S-UI 实例。
- 希望用同一套配置模板管理多个站点。
- 希望用工具重复执行 `check -> diagnose -> bootstrap -> configure-panel -> issue-cert -> configure-https -> create-api-token -> api-export -> plan-apply -> apply`。
- 出口既可以使用 VPS 默认直连出口，也可以使用住宅 SOCKS 上游出口。

暂不覆盖：

- 自动创建云主机或修改云安全组。
- 直接写 S-UI SQLite 数据库。
- 大规模集群编排。
- Web UI。

## 仓库结构

```text
bin/                    # 命令入口
src/sui_deployer/       # 工具业务逻辑
templates/config/       # 配置样例
templates/payloads/     # 按 S-UI 版本隔离的 API payload 模板
templates/remote/       # 上传到 VPS 执行的轻量 shell 模板
docs/                   # 新手手册、运维手册、设计文档
examples/               # 可提交的站点工作目录样例
tests/                  # 本地单元测试和 fixture
```

仓库内禁止保存真实敏感信息，包括 SSH 私钥、root 密码、S-UI 面板密码、API token、订阅完整链接、Reality 私钥、TLS 私钥、客户端 UUID、Trojan 密码、住宅代理凭据，以及 S-UI 数据库原始备份。

## 工作目录

真实站点数据应放在仓库外部的工作目录。推荐结构：

```text
<workdir>/
  sites/
    <site-id>/
      site.env
      logs/
      backups/
      generated/
      api-export/
  shared/
    ssh-keys/
    secrets/
```

每台 VPS/EC2 使用一个独立的 `<site-id>`。`site.env` 保存该站点的真实配置，日志、备份、API 导出和生成计划都写入同一个站点目录。

## 阅读顺序

1. [docs/runbooks/beginner-runbook.md](docs/runbooks/beginner-runbook.md)：面向新手的 S-UI 手动搭建步骤。
2. [docs/runbooks/tool-assisted-deployment.md](docs/runbooks/tool-assisted-deployment.md)：如何使用本工具完成端到端部署。
3. [docs/templates/setup-checklist.md](docs/templates/setup-checklist.md)：部署检查清单。
4. [templates/config/env.example](templates/config/env.example)：完整配置字段说明。
5. [docs/templates/node-config-template.md](docs/templates/node-config-template.md)：TLS、出站、入站和客户端配置记录模板。
6. [docs/templates/acceptance-record-template.md](docs/templates/acceptance-record-template.md)：验收记录模板。
7. [docs/runbooks/security-and-operations.md](docs/runbooks/security-and-operations.md)：安全、备份、轮换和泄露处理。
8. [docs/design/workspace-layout-and-tech-stack.md](docs/design/workspace-layout-and-tech-stack.md)：目录设计和技术栈说明。
9. [docs/design/api-automation-evaluation.md](docs/design/api-automation-evaluation.md)：S-UI API 自动化能力评估。
10. [docs/design/automation-plan.md](docs/design/automation-plan.md)：自动化路线图。

## 快速开始

以下示例使用仓库外部的 `$HOME/s-ui-deployer-work` 作为工作目录，使用 `my-site` 作为站点名。实际使用时可以替换成自己的目录和站点名。

### 1. 准备云主机、域名和安全组

需要准备：

- VPS/EC2 公网 IPv4。
- SSH 登录用户名，AWS Ubuntu 通常是 `ubuntu`。
- SSH 私钥文件。
- Ubuntu 22.04 LTS 或兼容的 Debian/Ubuntu 系统。
- 一个解析到 VPS/EC2 公网 IPv4 的域名。
- 如果使用住宅 SOCKS 出口，需要准备代理服务器、端口、用户名和密码。

云安全组建议开放：

```text
TCP: 22, 80, 2095, 2096, 443, 41101
UDP: 59501, 443
```

如果 Hysteria2 使用 `8443/udp`，则额外开放或改为开放 UDP `8443`。

### 2. 创建站点工作目录

```bash
export SUI_WORKDIR="$HOME/s-ui-deployer-work"
export SITE_ID="my-site"

mkdir -p "$SUI_WORKDIR/sites/$SITE_ID"
cp -R examples/site-workspace-template/. "$SUI_WORKDIR/sites/$SITE_ID/"
mv "$SUI_WORKDIR/sites/$SITE_ID/site.env.example" "$SUI_WORKDIR/sites/$SITE_ID/site.env"
mkdir -p "$SUI_WORKDIR/sites/$SITE_ID"/{logs,backups,generated,api-export}
```

编辑：

```text
$SUI_WORKDIR/sites/$SITE_ID/site.env
```

### 3. 填写基础配置

最小必填字段：

```bash
SITE_ID="my-site"
VPS_HOST="203.0.113.10"
SSH_USER="ubuntu"
SSH_KEY_PATH="/absolute/path/to/private-key.pem"
DOMAIN="panel.example.com"

WEB_PORT="2095"
WEB_PATH="/replace-with-random-panel-path/"
SUB_PORT="2096"
SUB_PATH="/replace-with-random-sub-path/"
```

说明：

- `SITE_ID` 是站点标识，默认也会作为主客户端名称。
- `SSH_KEY_PATH` 可以指向任意本机私钥路径；工具会自动把权限修正为 `600`。
- `WEB_PATH` 和 `SUB_PATH` 必须是长随机路径，并且使用 `/xxx/` 格式。
- `ROOT_PASSWORD` 可以留空；部署前应由密码管理器或安全随机生成器生成高强度密码后写入私密 `site.env`。
- `SUI_INITIAL_ADMIN_USERNAME` 可以留空；默认使用 S-UI 初始化生成的用户名。
- `SUI_INITIAL_ADMIN_PASSWORD` 可以留空；部署时可由工具配置为高强度随机密码。

### 4. 选择出站模式

`OUTBOUND_MODE` 支持三种写法：

```bash
OUTBOUND_MODE="direct"  # 使用 VPS 默认出口
OUTBOUND_MODE="socks"   # 使用住宅 SOCKS 出口
OUTBOUND_MODE=""        # 自动推断：代理服务器和端口为空则 direct，否则 socks
```

**使用 VPS 默认 direct 出口**

```bash
OUTBOUND_MODE="direct"
OUTBOUND_TAG="socks-residential"
OUTBOUND_TYPE="socks"
OUTBOUND_SERVER=""
OUTBOUND_PORT=""
OUTBOUND_USERNAME=""
OUTBOUND_PASSWORD=""
```

这种模式不会创建住宅 SOCKS 出站。`apply` 会把 S-UI 默认路由 `route.final` 设置为 `direct`，最终出口 IP 应为 VPS/EC2 公网 IP。

**使用住宅 SOCKS 出口**

```bash
OUTBOUND_MODE="socks"
OUTBOUND_TAG="socks-residential"
OUTBOUND_TYPE="socks"
OUTBOUND_SERVER=""      # 填住宅代理服务器地址
OUTBOUND_PORT=""        # 填住宅代理端口
OUTBOUND_USERNAME=""    # 需要认证时填写
OUTBOUND_PASSWORD=""    # 需要认证时填写
```

这种模式会创建或编辑住宅 SOCKS 出站，并把 S-UI 默认路由 `route.final` 设置为 `OUTBOUND_TAG`。最终出口 IP 应为住宅代理出口 IP。

### 5. 本地配置检查

```bash
bin/sui-deploy check "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令只读取本地配置，不连接远端。它会检查必填字段、端口格式、路径格式、出站模式、TLS tag 绑定和 SSH 私钥权限。

### 6. 远端只读诊断

```bash
bin/sui-deploy diagnose "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令通过 SSH 只读检查远端，不修改系统。重点确认 SSH 可登录、当前用户可 `sudo`、系统版本符合预期、UFW 状态和域名解析。

### 7. 安装 S-UI

```bash
bin/sui-deploy bootstrap "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令会安装依赖、设置 root 密码、安装 S-UI、处理安装过程中的交互提示、解析初始化管理员信息，并检查 `s-ui.service` 状态。

### 8. 配置面板和订阅基础信息

```bash
bin/sui-deploy configure-panel "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令会配置 Web 面板端口和路径、订阅端口和路径、管理员账号密码，并重启 S-UI 服务。

### 9. 申请 SSL 证书

确认云安全组已经开放 TCP `80`，然后执行：

```bash
bin/sui-deploy issue-cert "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

工具使用 S-UI 自带的 SSL 证书流程申请证书，并验证最终使用路径：

```text
/root/cert/<domain>/fullchain.pem
/root/cert/<domain>/privkey.pem
```

S-UI/acme.sh 输出中也可能出现签发工作目录，例如：

```text
/root/.acme.sh/<domain>_ecc/<domain>.cer
/root/.acme.sh/<domain>_ecc/<domain>.key
```

这是 acme.sh 的签发和续签目录。面板、订阅和 TLS 模板统一使用 `/root/cert/<domain>/` 下的 `fullchain.pem` 和 `privkey.pem`。

### 10. 启用面板和订阅 HTTPS

```bash
bin/sui-deploy configure-https "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令通过 S-UI Web API 绑定 Web/订阅域名、端口、路径和证书文件。

### 11. 创建 API Token

```bash
bin/sui-deploy create-api-token "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令会创建 S-UI API token，并写回站点私密配置文件。API token 不应提交到 git 仓库。

### 12. 导出现有 API 状态

```bash
bin/sui-deploy api-export "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

输出位置：

```text
$SUI_WORKDIR/sites/$SITE_ID/api-export/load.raw.json
$SUI_WORKDIR/sites/$SITE_ID/api-export/load.summary.json
```

`load.raw.json` 可能包含敏感配置，只能保存在工作目录。

### 13. 生成执行计划

```bash
bin/sui-deploy plan-apply "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令不会修改远端。它会读取 `/apiv2/load`，生成 Reality 密钥，规划 TLS 模板、出站、路由、4 个入站和主客户端。

出站行为：

- `OUTBOUND_MODE="socks"`：计划创建或编辑住宅 SOCKS 出站，并把 `route.final` 指向 `OUTBOUND_TAG`。
- `OUTBOUND_MODE="direct"`：不创建住宅 SOCKS 出站，并把 `route.final` 设置为 `direct`。

输出位置：

```text
$SUI_WORKDIR/sites/$SITE_ID/generated/plan-apply.raw.json
$SUI_WORKDIR/sites/$SITE_ID/generated/plan-apply.redacted.json
```

检查脱敏计划时，重点确认主客户端名称等于 `SITE_ID`，并关联全部 4 个入站。

### 14. 应用配置

```bash
bin/sui-deploy apply "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令会修改远端。执行顺序：

1. 备份 S-UI 数据库、服务文件和证书目录。
2. 调用 `/apiv2/save` 应用 TLS 模板。
3. 按 `OUTBOUND_MODE` 应用出站和默认路由。
4. 调用 `/apiv2/save` 应用 4 个入站。
5. 创建或编辑主客户端，名称使用 `SITE_ID`，并挂载全部 4 个入站。
6. 重启 sing-box core。
7. 写入脱敏 apply 结果。

备份位置：

```text
$SUI_WORKDIR/sites/$SITE_ID/backups/
```

### 15. 验证结果

再次执行：

```bash
bin/sui-deploy diagnose "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy api-export "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

期望状态：

```text
s-ui.service active
TCP 2095 listening
TCP 2096 listening
TCP 443 listening
TCP 41101 listening
UDP 59501 listening
UDP 443 listening 或 UDP 8443 listening
```

API 摘要期望：

```text
tls: 3
clients: 1
inbounds: 4
```

出站数量按模式判断：

```text
OUTBOUND_MODE=socks: outbounds 通常包含 direct 和住宅 SOCKS 出站
OUTBOUND_MODE=direct: 不需要额外住宅 SOCKS 出站，默认路由为 direct
```

浏览器验证地址：

```text
https://<DOMAIN>:2095/<WEB_PATH>/
```

登录后检查：

- TLS 管理中存在 `reality`、`tls`、`hy2-tls`。
- 入站管理中存在 VLESS REALITY、TUIC、Hysteria2、Trojan WebSocket/TLS。
- 客户端管理中主客户端名称等于 `SITE_ID`，并关联 4 个入站。
- 订阅链接可打开或可被 Clash Verge、Shadowrocket、Mihomo 等客户端导入。
- `socks` 模式下，访问 IP 检测网站应显示住宅代理出口 IP。
- `direct` 模式下，访问 IP 检测网站应显示 VPS/EC2 公网 IP。

## 命令参考

```bash
bin/sui-deploy check "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy diagnose "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy bootstrap "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy configure-panel "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy issue-cert "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy configure-https "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy create-api-token "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy backup "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy api-export "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy plan-apply "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy apply "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

命令安全边界：

- `check` 只做本地配置校验。
- `diagnose` 只读 SSH 检查。
- `plan-apply` 只生成计划，不修改远端。
- `bootstrap`、`configure-panel`、`issue-cert`、`configure-https`、`create-api-token`、`apply` 会修改远端。
- `apply` 会先备份，再调用 S-UI API。

## 技术栈

v1 采用 `Python 3 标准库优先 + OpenSSH/scp + 少量远端 Bash + S-UI /apiv2`。

选择这套技术栈的原因：

- Python 适合处理 `.env`、JSON、HTTP API、模板渲染、日志和脱敏输出。
- OpenSSH/scp 是 VPS 部署的通用基础设施。
- 远端 Bash 只承担系统级操作，例如安装依赖、检查服务、申请证书和备份文件。
- S-UI 面板配置优先通过 `/apiv2` 完成，减少对终端输出解析的依赖。
- 不引入 Terraform、Ansible、数据库或 Web UI，保持首版工具简单可审计。
