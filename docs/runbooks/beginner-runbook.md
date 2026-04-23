# S-UI 新手搭建手册

本文档从一台新的 AWS EC2 / VPS 开始，按面板操作一步一步搭建 S-UI：安装面板、申请 SSL 证书、创建 TLS 模板、创建住宅代理出站、创建客户端、创建 4 个入站，并验证客户端订阅和出口 IP。

本文按 S-UI v1.4.1 编写。不同版本的菜单名称可能略有变化，但配置顺序和字段含义应保持一致。

核心顺序：

```text
安装 S-UI -> 申请 SSL 证书 -> 配置面板/订阅 HTTPS
-> 创建 TLS 模板 -> 创建出站 -> 创建客户端
-> 创建入站并绑定 TLS/客户端 -> 导入订阅验证
```

## 1. 准备材料

部署前准备：

- 一台 AWS EC2 或其它 VPS，推荐 Ubuntu 22.04 或 Debian 12。
- VPS 公网 IP，例如 `203.0.113.10`。
- SSH 登录用户，例如 AWS 常见为 `ubuntu`。
- SSH 私钥，例如 `your-key.pem`。
- 一个域名，例如 `panel.example.com`。
- 一个可用的住宅代理上游，通常是 SOCKS5 或 HTTP 代理。
- 一个密码管理器，推荐 1Password、系统钥匙串或同类工具。
- 客户端软件，例如 Clash Verge Rev、Shadowrocket、Mihomo Party。

需要提前生成并保存：

- root 高强度密码。
- 面板路径，例如 `/app-一串随机字符/`。
- 订阅路径，例如 `/sub-一串随机字符/`。
- WebSocket 路径，例如 `/ws-一串随机字符`。
- 住宅代理用户名和密码。
- 客户端名称，例如 `alice-phone`。

真实值只写入 `<workdir>/sites/<site-id>/site.env` 或密码管理器，不要写进公开文档。

## 2. 修正 SSH 私钥权限

在本机执行：

```bash
chmod 600 /path/to/your-key.pem
```

连接 VPS：

```bash
ssh -i /path/to/your-key.pem ubuntu@203.0.113.10
```

如果提示 `Please login as the user "ubuntu" rather than the user "root"`，说明服务器禁止 root 直接登录，继续使用 `ubuntu`。

## 3. 检查系统和 sudo

登录 VPS 后执行：

```bash
whoami
uname -a
sudo -n true && echo "sudo ok"
```

预期：

- `whoami` 输出 `ubuntu`、`debian` 或 `root`。
- 系统是 Linux。
- `sudo ok` 能输出。

如果 `sudo -n true` 失败，先确认云服务器镜像和 SSH 用户是否正确。

## 4. 设置 root 密码

AWS 默认通常用普通用户登录，再通过 `sudo` 执行管理员命令。后续自动化可能需要 root 密码，但默认不建议开启 SSH root 密码登录。

用 1Password 或同类工具生成 24 位以上随机密码，然后在 VPS 上执行：

```bash
sudo passwd root
```

按提示输入两次新密码。

检查 root 密码是否可用于本机切换：

```bash
su -
exit
```

不要默认修改 SSH 配置里的：

```text
PermitRootLogin yes
PasswordAuthentication yes
```

设置 root 密码不等于允许 root 通过 SSH 密码登录。

## 5. 更新系统依赖

执行：

```bash
sudo apt-get update
sudo apt-get install -y curl wget ca-certificates tar gzip unzip nano socat openssl
```

检查时间：

```bash
date
timedatectl status
```

如果服务器时间明显不对，先修正 NTP。证书和 TLS 依赖时间准确。

## 6. 安装 S-UI

以 root 权限执行安装：

```bash
sudo -i
bash <(curl -Ls https://raw.githubusercontent.com/alireza0/s-ui/master/install.sh)
```

安装过程中会出现提示：

```text
Do you want to continue with the modification [y/n]?
```

这里输入：

```text
n
```

原因：当前手册先使用安装脚本自动生成的初始管理员用户名和密码，确认面板可登录后，再通过面板逐步配置端口、路径、证书、TLS 和节点。

首次安装选择 `n` 后，脚本会输出类似信息：

```text
this is a fresh installation,will generate random login info for security concerns:
###############################################
username:<initial-username>
password:<initial-password>
###############################################
```

把这两个值先临时记录到密码管理器或 `work/sites/<site-id>/site.env`：

```bash
SUI_INITIAL_ADMIN_USERNAME=""
SUI_INITIAL_ADMIN_PASSWORD=""
SUI_INITIAL_ADMIN_SOURCE="install-output"
```

真实用户名和密码只填入 `work/sites/<site-id>/site.env` 或密码管理器，不要写入公开文档。

安装结束后会输出面板访问 URL。退出 root shell：

```bash
exit
```

检查服务：

```bash
sudo systemctl is-active s-ui.service
sudo systemctl status s-ui.service --no-pager
```

预期状态是 `active`。

如果忘记记录初始用户名或密码，可以在 VPS 上执行：

```bash
sudo /usr/local/s-ui/sui admin -show
```

或进入 `sudo s-ui` 菜单查看管理员信息。

## 7. 验证初始面板登录

用安装输出的 URL 打开面板。常见默认形式：

```text
http://VPS_PUBLIC_IP:2095/app/
```

使用刚记录的初始用户名和密码登录。必须确认登录成功，再继续下一步。

登录成功后，把初始管理员信息保存到私密配置或密码管理器。不要提交仓库。

## 8. AWS 安全组端口

AWS EC2 默认未启用 UFW，主要防火墙是 AWS Security Group。先检查 VPS 内 UFW：

```bash
sudo ufw status verbose || true
```

AWS 默认通常是：

```text
Status: inactive
```

本文按 UFW 未启用处理。需要在 AWS 安全组开放：

| 用途 | 协议 | 示例端口 | 来源 |
| --- | --- | --- | --- |
| SSH | TCP | `22` | 建议你的公网 IP，临时可 `0.0.0.0/0` |
| ACME HTTP 验证 | TCP | `80` | `0.0.0.0/0` |
| 面板 HTTPS | TCP | `2095` | `0.0.0.0/0` |
| 订阅 HTTPS | TCP | `2096` | `0.0.0.0/0` |
| VLESS REALITY | TCP | `443` | `0.0.0.0/0` |
| TUIC | UDP | `59501` | `0.0.0.0/0` |
| Hysteria2 | UDP | `8443` 或 `443` | `0.0.0.0/0` |
| Trojan WS/TLS | TCP | `41101` | `0.0.0.0/0` |

申请 SSL 证书前，`TCP 80` 必须先打开。证书签发成功后，是否关闭 `TCP 80` 取决于续签方式；如果使用 HTTP standalone 自动续签，建议保持可达或在续签时再临时开放。

## 9. 配置域名 DNS

在域名服务商后台添加 A 记录：

```text
主机名：panel
记录类型：A
记录值：VPS 公网 IP
```

示例：

```text
panel.example.com -> 203.0.113.10
```

本机检查：

```bash
dig +short panel.example.com
```

如果没有 `dig`，使用：

```bash
nslookup panel.example.com
```

解析结果必须包含 VPS 公网 IP。

## 10. 使用 S-UI 申请 SSL 证书

确认 AWS 安全组已经开放 `TCP 80` 后，进入菜单：

```bash
sudo s-ui
```

按以下菜单操作：

```text
19. SSL Certificate Management
1. Get SSL
```

按提示输入你的域名：

```text
panel.example.com
```

出现端口提示时：

```text
please choose which port do you use,default will be 80 port:
```

直接回车，使用默认 `80`。

证书生成后，S-UI/acme 会把文件安装到：

```text
/root/cert/<domain>/fullchain.pem
/root/cert/<domain>/privkey.pem
```

这里容易混淆两个路径：

```text
/root/.acme.sh/<domain>_ecc/<domain>.cer
/root/.acme.sh/<domain>_ecc/<domain>.key
```

这组是 `acme.sh` 的签发和续签工作目录。S-UI 菜单在签发完成后还会执行安装步骤，把最终给面板和节点配置使用的文件复制/安装到：

```text
/root/cert/<domain>/fullchain.pem
/root/cert/<domain>/privkey.pem
```

所以后续填写 Web HTTPS、订阅 HTTPS、普通 TLS 模板、Hysteria2 TLS 模板时，统一使用 `/root/cert/<domain>/...` 这组路径。`.cer` / `.key` 和 `.pem` 后缀不同是正常现象，不影响最终使用。

示例：

```text
/root/cert/panel.example.com/fullchain.pem
/root/cert/panel.example.com/privkey.pem
```

在 VPS 上确认文件存在：

```bash
sudo test -f /root/cert/panel.example.com/fullchain.pem && echo "fullchain ok"
sudo test -f /root/cert/panel.example.com/privkey.pem && echo "privkey ok"
```

把路径保存到私密配置：

```bash
SSL_HTTP_PORT="80"
SSL_CERT_FULLCHAIN_PATH="/root/cert/panel.example.com/fullchain.pem"
SSL_CERT_KEY_PATH="/root/cert/panel.example.com/privkey.pem"
SSL_CERT_SOURCE="s-ui-acme"
```

不要把证书私钥内容复制进文档，只记录路径。

## 11. 配置面板和订阅 HTTPS

登录 S-UI 面板，进入面板设置或系统设置。按以下字段填写：

| 字段 | 填写 |
| --- | --- |
| Web 域名 | `panel.example.com` |
| Web 端口 | `2095` |
| Web 路径 | 长随机路径，例如 `/app-9d4f0c7a8b2e4f31/` |
| Web 证书 | `/root/cert/panel.example.com/fullchain.pem` |
| Web 私钥 | `/root/cert/panel.example.com/privkey.pem` |
| 订阅域名 | `panel.example.com` |
| 订阅端口 | `2096` |
| 订阅路径 | 长随机路径，例如 `/sub-14cf93d7a0b65e2d/` |
| 订阅证书 | `/root/cert/panel.example.com/fullchain.pem` |
| 订阅私钥 | `/root/cert/panel.example.com/privkey.pem` |

保存后重启：

```bash
sudo systemctl restart s-ui.service
sudo systemctl is-active s-ui.service
```

用浏览器打开新地址：

```text
https://panel.example.com:2095/app-9d4f0c7a8b2e4f31/
```

确认可以登录。

## 12. 创建 TLS 模板：REALITY

进入面板：

```text
TLS 管理 -> 新建 TLS
```

填写：

| 字段 | 填写 |
| --- | --- |
| 名称 | `reality` |
| 类型 | `REALITY` |
| 生成密钥 | 点击 S-UI 自带生成按钮 |
| 私钥 | 使用生成的 PrivateKey |
| 公钥 | 使用生成的 PublicKey，客户端链接会用到 |
| 伪装握手目标 | `aws.amazon.com:443` 或其它稳定 HTTPS 域名 |
| uTLS 指纹 | `chrome` |
| short id | 使用 S-UI 生成值，或填随机短值 |

需要勾选或选择：

- TLS 类型选择 `REALITY`。
- uTLS 打开，并选择 `chrome`。
- REALITY 打开。

保存，后续 VLESS 入站会绑定这个 TLS 模板。

后续自动化可用 API 生成密钥：

```text
GET /apiv2/keypairs?k=reality
```

## 13. 创建 TLS 模板：普通 TLS

进入：

```text
TLS 管理 -> 新建 TLS
```

填写：

| 字段 | 填写 |
| --- | --- |
| 名称 | `tls` |
| 类型 | `TLS` |
| 证书路径 | `/root/cert/panel.example.com/fullchain.pem` |
| 私钥路径 | `/root/cert/panel.example.com/privkey.pem` |
| Server Name / SNI | `panel.example.com` |
| ALPN | `h3,h2,http/1.1` |

需要勾选：

- TLS 启用。
- SNI 启用。
- ALPN 启用。
- 客户端选项里的 `Allow Insecure` / `允许不安全` 按当前手册要求勾选。

说明：这里的“允许不安全”是给客户端侧生成链接时使用的兼容选项。如果你有严格证书校验要求，可以在后续验证无误后再评估关闭。

保存，后续 TUIC 和 Trojan WS/TLS 入站会绑定这个 TLS 模板。

## 14. 创建 TLS 模板：Hysteria2 专用 TLS

Hysteria2 单独建一个 TLS 模板，避免和 TUIC/Trojan 的 TLS 配置互相影响。

进入：

```text
TLS 管理 -> 新建 TLS
```

填写：

| 字段 | 填写 |
| --- | --- |
| 名称 | `hy2-tls` |
| 类型 | `TLS` |
| 证书路径 | `/root/cert/panel.example.com/fullchain.pem` |
| 私钥路径 | `/root/cert/panel.example.com/privkey.pem` |
| Server Name / SNI | `panel.example.com` |
| ALPN | 按 S-UI 推荐默认；如需显式填写，先使用 `h3` |

需要勾选：

- TLS 启用。
- SNI 启用。
- 如面板有 ALPN 选项，按需要启用。
- 客户端选项里的 `Allow Insecure` / `允许不安全` 按当前手册要求勾选。

保存，后续 Hysteria2 入站绑定这个 TLS 模板。

## 15. 创建住宅代理出站

进入：

```text
出站管理 -> 新建出站
```

填写：

| 字段 | 填写 |
| --- | --- |
| 类型 | `socks` |
| Tag | `socks-chile-static-res` 或配置文件里的 `OUTBOUND_TAG` |
| 服务器 | 住宅代理服务商提供的 IP 或域名 |
| 端口 | 住宅代理端口 |
| 用户名 | 住宅代理用户名 |
| 密码 | 住宅代理密码 |
| SOCKS 版本 | `5` |

保存后，进入基础配置或路由配置，把默认出站设置为该 tag：

```text
route.final = socks-chile-static-res
```

保存并重启 S-UI：

```bash
sudo systemctl restart s-ui.service
```

## 16. 创建客户端

进入：

```text
客户端管理 -> 新建客户端
```

填写：

| 字段 | 填写 |
| --- | --- |
| 名称 | `alice-phone`、`alice-laptop` 或其它设备名 |
| 启用 | 打开 |
| 流量限制 | 不限制则填 `0` 或保持默认 |
| 过期时间 | 不限制则填 `0` 或保持默认 |
| 备注 | 写清楚用途，例如 `primary test client` |

先保存。后续创建入站时再绑定这个客户端。

## 17. 创建 VLESS REALITY 入站

进入：

```text
入站管理 -> 新建入站
```

填写：

| 字段 | 填写 |
| --- | --- |
| 协议 / 类型 | `vless` |
| Tag | `vless-reality` |
| 监听地址 | `::` |
| 监听端口 | `443` |
| TLS | 选择前面创建的 `reality` 模板 |
| 传输 | TCP / 默认 |
| 客户端 | 绑定刚创建的客户端 |
| 出站 | 保持默认路由，或显式选择 `socks-chile-static-res` |

需要选择或勾选：

- 协议选择 `vless`。
- TLS 选择 `reality`。
- 传输保持默认 TCP。
- 客户端必须绑定，否则订阅里不会生成可用用户配置。

AWS 安全组：

```text
443/tcp
```

保存后检查：

```bash
sudo ss -lntp | grep ':443'
```

## 18. 创建 TUIC 入站

进入：

```text
入站管理 -> 新建入站
```

填写：

| 字段 | 填写 |
| --- | --- |
| 协议 / 类型 | `tuic` |
| Tag | `tuic-59501` |
| 监听地址 | `::` |
| 监听端口 | `59501` |
| 拥塞控制 | `bbr` |
| TLS | 选择 `tls` 模板 |
| ALPN | `h3,h2,http/1.1` |
| 客户端 | 绑定刚创建的客户端 |

需要选择或勾选：

- 协议选择 `tuic`。
- TLS 选择普通 `tls` 模板。
- ALPN 保持 `h3,h2,http/1.1`。
- 客户端必须绑定。

AWS 安全组：

```text
59501/udp
```

保存后检查：

```bash
sudo ss -lunp | grep ':59501'
```

## 19. 创建 Hysteria2 入站

进入：

```text
入站管理 -> 新建入站
```

填写：

| 字段 | 填写 |
| --- | --- |
| 协议 / 类型 | `hysteria2` |
| Tag | `hysteria2` |
| 监听地址 | `::` |
| 监听端口 | 建议 `8443`；如果复用 `443/udp`，必须记录 |
| TLS | 选择 `hy2-tls` 模板 |
| 客户端 | 绑定刚创建的客户端 |

需要选择或勾选：

- 协议选择 `hysteria2`。
- TLS 选择 `hy2-tls`，不要直接复用普通 `tls`。
- 客户端必须绑定。

AWS 安全组：

```text
8443/udp
```

如果你使用 `443/udp`，则开放：

```text
443/udp
```

保存后检查：

```bash
sudo ss -lunp | grep -E ':(8443|443)'
```

## 20. 创建 Trojan WS/TLS 入站

进入：

```text
入站管理 -> 新建入站
```

填写：

| 字段 | 填写 |
| --- | --- |
| 协议 / 类型 | `trojan` |
| Tag | `trojan-ws` |
| 监听地址 | `::` |
| 监听端口 | `41101` |
| TLS | 选择 `tls` 模板 |
| 传输 | `WebSocket` |
| WebSocket 路径 | 长随机路径，例如 `/ws-9b21e8c4` |
| Host Header | `aws.amazon.com` 或其它伪装域名 |
| 客户端 | 绑定刚创建的客户端 |

需要选择或勾选：

- 协议选择 `trojan`。
- TLS 选择普通 `tls` 模板。
- 传输选择 `WebSocket`。
- WebSocket path 必须和客户端订阅生成值一致。
- 客户端必须绑定。

AWS 安全组：

```text
41101/tcp
```

保存后检查：

```bash
sudo ss -lntp | grep ':41101'
```

## 21. 生成并导入订阅

进入：

```text
客户端管理 -> 打开客户端详情 -> 复制订阅链接
```

订阅链接通常类似：

```text
https://panel.example.com:2096/订阅路径/...
```

注意：

- 订阅链接等同于钥匙，不要发到公开群。
- 如果订阅泄露，应立即重置订阅路径或重建客户端。

在客户端导入：

- Clash Verge Rev：配置 -> 新建 -> URL 导入。
- Shadowrocket：右上角加号 -> 类型选择 Subscribe。
- Mihomo Party：Profiles -> New Profile -> URL。

导入后确认至少看到：

- `vless-reality`
- `tuic-59501`
- `hysteria2`
- `trojan-ws`

至少测试一个节点可连通。

## 22. 验证出口 IP

在客户端启用代理后访问：

```text
https://api.ipify.org
https://ipinfo.io
https://browserleaks.com/ip
```

预期看到住宅代理出口 IP，而不是 VPS IP，也不是本机真实 IP。

如果出口 IP 是 VPS，优先检查：

- 默认路由 `route.final` 是否指向住宅代理出站。
- 入站是否显式覆盖了出站。
- 住宅代理出站是否可用。

## 23. 检查服务状态

在 VPS 上执行：

```bash
sudo systemctl is-active s-ui.service
sudo ss -lntup | grep -E ':(443|2095|2096|59501|8443|41101)'
sudo journalctl -u s-ui.service -n 50 --no-pager
```

日志可能包含访问域名和来源 IP。复制给别人排障前先脱敏。

## 24. 备份

至少备份：

```text
/usr/local/s-ui/db/s-ui.db
/usr/local/s-ui/db/s-ui.db-wal
/usr/local/s-ui/db/s-ui.db-shm
/etc/systemd/system/s-ui.service
/usr/local/s-ui/
```

推荐：

```bash
sudo systemctl stop s-ui.service
sudo tar -czf /tmp/s-ui-backup-$(date +%Y%m%d-%H%M%S).tar.gz /usr/local/s-ui /etc/systemd/system/s-ui.service
sudo systemctl start s-ui.service
```

下载到本地私密目录：

```bash
scp -i /path/to/your-key.pem ubuntu@203.0.113.10:/tmp/s-ui-backup-YYYYMMDD-HHMMSS.tar.gz <workdir>/sites/<site-id>/backups/
```

`work/backups/` 默认不会提交仓库。

## 25. 常见故障

| 现象 | 优先检查 | 处理 |
| --- | --- | --- |
| SSH 私钥被拒绝 | 私钥权限 | 本机执行 `chmod 600 key.pem` |
| 安装后不知道账号密码 | 安装输出或 `admin -show` | 查安装日志，或执行 `sudo /usr/local/s-ui/sui admin -show` |
| SSL 签发失败 | DNS、TCP 80、安全组 | 确认域名解析到 VPS，安全组开放 `80/tcp` |
| 面板打不开 | 安全组、端口、路径、证书 | 先 `curl -Ik` 检查，再看 `journalctl` |
| 订阅拉不下来 | 订阅端口和路径 | 确认 `SUB_PORT` 和 `SUB_PATH` |
| 节点测速超时 | 安全组协议不对 | UDP 节点要放行 UDP，不是 TCP |
| VLESS REALITY 失败 | REALITY TLS 模板 | 检查 private key、short id、握手目标、uTLS chrome |
| TUIC/Hysteria2 失败 | UDP 和 TLS | 检查 UDP 安全组、TLS 模板、ALPN |
| Trojan WS 失败 | WebSocket | 检查 WS 路径、Host Header、TLS 模板 |
| 出口 IP 是 VPS | 路由 final 没走住宅出站 | 检查默认出站和出站 tag |
| 出口 IP 是本机 | 客户端未启用代理或泄漏 | 开启系统代理，检查 DNS/WebRTC/QUIC |

## 26. 完成标准

部署完成必须满足：

- SSH 可以登录。
- root 密码已生成并保存到私密位置。
- 安装时选择了不继续修改，即提示处输入 `n`。
- 初始管理员用户名和密码已记录、可登录、已私密保存。
- AWS 安全组已开放需要的 TCP/UDP 端口。
- UFW 未启用，或已明确记录并放行对应端口。
- SSL 证书已签发，证书路径和私钥路径已记录。
- `reality`、`tls`、`hy2-tls` 三类 TLS 模板已创建。
- 住宅代理出站已创建，默认路由指向该出站。
- 客户端已创建。
- 4 个入站都已创建并绑定正确 TLS 模板和客户端。
- 订阅能导入客户端。
- 至少 1 个节点实际可连通。
- 目标网站看到住宅代理出口 IP。
- 真实配置、日志、备份都保存在 `work/` 或密码管理器，不提交仓库。
