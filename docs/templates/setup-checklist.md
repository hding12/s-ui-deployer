# S-UI 部署检查清单

复制本文件到 `<workdir>/sites/<site-id>/generated/setup-checklist-YYYYMMDD.md` 后填写。真实记录默认不提交仓库。

## 部署前

- [ ] VPS 已购买。
- [ ] VPS 系统是 Ubuntu/Debian。
- [ ] 已确认 VPS 公网 IP。
- [ ] 已确认 SSH 用户，例如 `ubuntu`。
- [ ] SSH 私钥已保存到本机私密位置。
- [ ] SSH 私钥权限已设置为 `600`。
- [ ] 域名已准备。
- [ ] 域名 A 记录已指向 VPS 公网 IP。
- [ ] AWS 安全组已开放 `80/tcp` 用于 SSL 证书申请。
- [ ] 住宅代理上游已准备。
- [ ] root 密码已生成并保存到密码管理器或 `work/shared/secrets/`。
- [ ] S-UI 面板密码已生成并保存。
- [ ] 面板路径已生成。
- [ ] 订阅路径已生成。
- [ ] WebSocket 路径已生成。
- [ ] `work/sites/<site-id>/site.env` 已填写真实配置。
- [ ] 真实配置文件权限已设置为 `600`。

## 服务器基础检查

- [ ] SSH 可登录。
- [ ] 当前用户可使用 `sudo`。
- [ ] 系统时间正确。
- [ ] 系统依赖已安装。
- [ ] root 密码已设置。
- [ ] 未开启 SSH root 密码登录，除非有明确记录。

## S-UI 安装

- [ ] S-UI 安装脚本执行成功。
- [ ] 安装提示 `Do you want to continue with the modification [y/n]?` 已输入 `n`。
- [ ] 初始管理员用户名已从安装输出或 `admin -show` 获取。
- [ ] 初始管理员密码已从安装输出或 `admin -show` 获取。
- [ ] 初始管理员账号已验证可以登录面板。
- [ ] 初始管理员信息已保存到密码管理器或 `work/sites/<site-id>/site.env`。
- [ ] `s-ui.service` 存在。
- [ ] `s-ui.service` 状态为 `active`。
- [ ] `/usr/local/s-ui/db/s-ui.db` 存在。
- [ ] BBR 已开启或记录为跳过。

## 面板和订阅

- [ ] AWS 安全组 `80/tcp` 在申请证书时可达。
- [ ] S-UI SSL Certificate Management 已成功签发证书。
- [ ] 证书路径 `/root/cert/<domain>/fullchain.pem` 已记录。
- [ ] 私钥路径 `/root/cert/<domain>/privkey.pem` 已记录。
- [ ] Web 域名已填写。
- [ ] Web 端口已设置。
- [ ] Web 路径已设置为长随机路径。
- [ ] Web HTTPS 可打开。
- [ ] 订阅域名已填写。
- [ ] 订阅端口已设置。
- [ ] 订阅路径已设置为长随机路径。
- [ ] 订阅 HTTPS 可拉取。

## TLS 模板

- [ ] `reality` TLS 模板已创建。
- [ ] REALITY 私钥/公钥已由 S-UI 生成或 API 生成。
- [ ] REALITY 伪装握手目标已填写。
- [ ] REALITY uTLS 指纹已选择 `chrome`。
- [ ] 普通 `tls` 模板已创建。
- [ ] 普通 `tls` 模板已填写证书和私钥路径。
- [ ] 普通 `tls` 模板已勾选 SNI。
- [ ] 普通 `tls` 模板已勾选 ALPN。
- [ ] 普通 `tls` 模板 ALPN 已填写 `h3,h2,http/1.1`。
- [ ] 普通 `tls` 模板已按当前策略勾选允许不安全。
- [ ] `hy2-tls` Hysteria2 专用 TLS 模板已创建。

## 出站和路由

- [ ] 住宅 SOCKS/HTTP 出站已创建。
- [ ] 出站 tag 已记录。
- [ ] 默认路由 final 已设置为住宅出站。
- [ ] 出口 IP 验证为住宅代理 IP。

## 入站和客户端

- [ ] 客户端已创建。
- [ ] VLESS REALITY 入站已创建，协议为 `vless`，TLS 绑定 `reality`，端口为 `443/tcp`。
- [ ] TUIC 入站已创建，协议为 `tuic`，TLS 绑定 `tls`，端口为 `59501/udp`。
- [ ] Hysteria2 入站已创建，协议为 `hysteria2`，TLS 绑定 `hy2-tls`，端口为 `8443/udp` 或已记录复用端口。
- [ ] Trojan WS/TLS 入站已创建，协议为 `trojan`，TLS 绑定 `tls`，传输为 `WebSocket`，端口为 `41101/tcp`。
- [ ] 所有入站都绑定到客户端。
- [ ] 云安全组已放行对应 TCP/UDP 端口。
- [ ] 客户端已导入订阅。
- [ ] 至少一个节点测速成功。

## 收尾

- [ ] 已创建初始备份。
- [ ] 备份已保存到 `work/backups/` 或其他私密位置。
- [ ] 验收记录已填写。
- [ ] 文档和记录已脱敏。
- [ ] 没有真实密码、私钥、token、订阅链接被提交仓库。
