# 使用 S-UI Deployer 完整部署

本文说明如何使用 S-UI Deployer 从空白 VPS/EC2 完成端到端部署。手动面板步骤见 [beginner-runbook.md](beginner-runbook.md)；本文以工具命令为主。

## 1. 准备信息

准备以下内容：

- VPS/EC2 公网 IPv4。
- SSH 登录用户名，例如 Ubuntu 镜像常用 `ubuntu`。
- SSH 私钥文件。
- 解析到该 VPS/EC2 的域名。
- 云安全组规则：
  - TCP：`22`、`80`、`2095`、`2096`、`443`、`41101`
  - UDP：`59501`，以及 Hysteria2 使用的 UDP 端口，例如 `443` 或 `8443`
- 如果使用住宅 SOCKS 出口，准备代理服务器、端口、用户名和密码。

## 2. 创建工作目录

真实配置不要放入 git 仓库。推荐把工作目录放在仓库外：

```bash
export SUI_WORKDIR="$HOME/s-ui-deployer-work"
export SITE_ID="my-site"

mkdir -p "$SUI_WORKDIR/sites/$SITE_ID"
cp -R examples/site-workspace-template/. "$SUI_WORKDIR/sites/$SITE_ID/"
mv "$SUI_WORKDIR/sites/$SITE_ID/site.env.example" "$SUI_WORKDIR/sites/$SITE_ID/site.env"
mkdir -p "$SUI_WORKDIR/sites/$SITE_ID"/{logs,backups,generated,api-export}
```

后续命令都使用：

```text
$SUI_WORKDIR/sites/$SITE_ID/site.env
```

## 3. 填写 site.env

基础字段：

```bash
SITE_ID="my-site"
VPS_HOST="203.0.113.10"
SSH_USER="ubuntu"
SSH_KEY_PATH="/absolute/path/to/private-key.pem"
SSH_PORT="22"
DOMAIN="panel.example.com"

WEB_PORT="2095"
WEB_PATH="/replace-with-random-panel-path/"
SUB_PORT="2096"
SUB_PATH="/replace-with-random-sub-path/"
```

密码字段可以先留空，但真实部署前应由密码管理器或安全随机生成器生成后写入私密配置：

```bash
ROOT_PASSWORD=""
ROOT_PASSWORD_SOURCE="generated"
ENABLE_ROOT_PASSWORD_LOGIN="false"

SUI_INITIAL_ADMIN_USERNAME=""
SUI_INITIAL_ADMIN_PASSWORD=""
```

工具会自动把本机 SSH 私钥权限修正为 `600`。设置 root 密码不等于开启 SSH root 密码登录，默认保持 `ENABLE_ROOT_PASSWORD_LOGIN="false"`。

## 4. 选择出站模式

使用 VPS 默认 direct 出口：

```bash
OUTBOUND_MODE="direct"
OUTBOUND_TAG="socks-residential"
OUTBOUND_TYPE="socks"
OUTBOUND_SERVER=""
OUTBOUND_PORT=""
OUTBOUND_USERNAME=""
OUTBOUND_PASSWORD=""
```

使用住宅 SOCKS 出口：

```bash
OUTBOUND_MODE="socks"
OUTBOUND_TAG="socks-residential"
OUTBOUND_TYPE="socks"
OUTBOUND_SERVER=""      # 填住宅代理服务器
OUTBOUND_PORT=""        # 填住宅代理端口
OUTBOUND_USERNAME=""    # 需要认证时填写
OUTBOUND_PASSWORD=""    # 需要认证时填写
```

`OUTBOUND_MODE=""` 时工具会自动推断：代理服务器和端口为空则按 `direct`，否则按 `socks`。

## 5. 本地检查

```bash
bin/sui-deploy check "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令不连接远端，只检查配置字段、路径、端口、出站模式和 SSH 私钥权限。

## 6. 远端只读诊断

```bash
bin/sui-deploy diagnose "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令通过 SSH 只读检查系统、sudo、UFW、DNS、S-UI 服务和监听端口，不修改远端。

## 7. 安装 S-UI

```bash
bin/sui-deploy bootstrap "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令会安装依赖、设置 root 密码、执行 S-UI 安装、处理安装交互提示、解析初始化管理员信息，并检查 `s-ui.service`。

## 8. 配置面板和订阅

```bash
bin/sui-deploy configure-panel "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令会配置 Web 面板端口/路径、订阅端口/路径、管理员账号密码，并重启 S-UI。

## 9. 申请 SSL 证书

确认云安全组已经开放 TCP `80`，然后执行：

```bash
bin/sui-deploy issue-cert "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

工具使用 S-UI 自带 SSL 证书流程申请证书，并验证最终使用路径：

```text
/root/cert/<domain>/fullchain.pem
/root/cert/<domain>/privkey.pem
```

acme.sh 的签发目录可能是 `/root/.acme.sh/<domain>_ecc/`，这是正常现象。面板、订阅和 TLS 模板统一使用 `/root/cert/<domain>/` 下的证书文件。

## 10. 启用 HTTPS

```bash
bin/sui-deploy configure-https "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令通过 S-UI Web API 绑定 Web/订阅域名、端口、路径和证书。

## 11. 创建 API Token

```bash
bin/sui-deploy create-api-token "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

API token 会写回私密 `site.env`，不要提交到 git 仓库。

## 12. 导出现有状态

```bash
bin/sui-deploy api-export "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

输出文件：

```text
$SUI_WORKDIR/sites/$SITE_ID/api-export/load.raw.json
$SUI_WORKDIR/sites/$SITE_ID/api-export/load.summary.json
```

`load.raw.json` 可能包含敏感配置，只能保存在工作目录。

## 13. 生成执行计划

```bash
bin/sui-deploy plan-apply "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

该命令不会修改远端。它会规划：

- 3 个 TLS 模板：`reality`、`tls`、`hy2-tls`。
- 出站和默认路由：
  - `socks` 模式创建或编辑住宅 SOCKS 出站，并把 `route.final` 指向 `OUTBOUND_TAG`。
  - `direct` 模式不创建住宅 SOCKS 出站，并把 `route.final` 设置为 `direct`。
- 4 个入站：VLESS REALITY、TUIC、Hysteria2、Trojan WebSocket/TLS。
- 1 个主客户端，名称默认等于 `SITE_ID`，并挂载全部 4 个入站。

输出文件：

```text
$SUI_WORKDIR/sites/$SITE_ID/generated/plan-apply.raw.json
$SUI_WORKDIR/sites/$SITE_ID/generated/plan-apply.redacted.json
```

先查看脱敏计划，确认没有明显错误后再执行 `apply`。

## 14. 应用配置

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

备份写入：

```text
$SUI_WORKDIR/sites/$SITE_ID/backups/
```

## 15. 验收

```bash
bin/sui-deploy diagnose "$SUI_WORKDIR/sites/$SITE_ID/site.env"
bin/sui-deploy api-export "$SUI_WORKDIR/sites/$SITE_ID/site.env"
```

期望：

- `s-ui.service active`。
- 面板端口和订阅端口监听正常。
- 4 个入站端口监听正常。
- API 摘要显示 `tls: 3`、`clients: 1`、`inbounds: 4`。
- 主客户端名称等于 `SITE_ID`，并关联全部 4 个入站。
- `socks` 模式下出口 IP 是住宅代理出口。
- `direct` 模式下出口 IP 是 VPS/EC2 公网 IP。

浏览器验证：

```text
https://<DOMAIN>:2095/<WEB_PATH>/
```

客户端验证：

- 复制订阅链接。
- 导入 Clash Verge、Shadowrocket、Mihomo 等客户端。
- 确认 VLESS、TUIC、Hysteria2、Trojan 都存在。
- 至少测试一个节点可连通。
- 访问 IP 检测网站确认出口符合出站模式预期。
