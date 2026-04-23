# 节点与入站配置记录模板

复制本文件到 `<workdir>/sites/<site-id>/generated/node-config-YYYYMMDD.md` 后填写。真实记录默认不提交仓库。

说明：

- S-UI 的“节点管理”对应 sing-box `endpoint`，例如 WireGuard/WARP。
- S-UI 的“入站管理”对应 sing-box `inbound`，例如 VLESS、TUIC、Hysteria2、Trojan。
- 客户端订阅里看到的可连接项目由入站、TLS、客户端和链接生成逻辑组合出来，和“节点管理”不是同一个对象。

## 基础信息

| 项目 | 值 |
| --- | --- |
| VPS 名称 |  |
| VPS 公网 IP |  |
| 域名 |  |
| S-UI 版本 |  |
| Web 端口 |  |
| Web 路径 |  |
| 订阅端口 |  |
| 订阅路径 |  |
| 默认出站 tag |  |
| SSL fullchain 路径 |  |
| SSL private key 路径 |  |

## TLS 模板配置记录

### TLS 模板：REALITY

| 字段 | 是否必填 | 面板填写值 | 自动化变量名 | 验证方式 |
| --- | --- | --- | --- | --- |
| 名称 | 是 | `reality` | `TLS_REALITY_TAG` | TLS 列表可见 |
| 类型 | 是 | `REALITY` | 固定值 | 类型显示为 REALITY |
| 私钥 | 是 | S-UI 生成 PrivateKey | `TLS_REALITY_PRIVATE_KEY` | 不公开，仅确认非空 |
| 公钥 | 是 | S-UI 生成 PublicKey | `TLS_REALITY_PUBLIC_KEY` | 客户端链接包含 public key |
| short id | 是 | S-UI 生成或随机短值 | `TLS_REALITY_SHORT_ID` | 客户端链接包含 short id |
| 伪装握手目标 | 是 | `aws.amazon.com:443` | `TLS_REALITY_HANDSHAKE_SERVER` / `TLS_REALITY_HANDSHAKE_PORT` | VLESS 连接成功 |
| uTLS 指纹 | 是 | `chrome` | `TLS_REALITY_UTLS_FINGERPRINT` | VLESS 连接成功 |

需要勾选或选择：

- TLS 类型选择 `REALITY`。
- REALITY 启用。
- uTLS 启用，指纹选择 `chrome`。

### TLS 模板：普通 TLS

| 字段 | 是否必填 | 面板填写值 | 自动化变量名 | 验证方式 |
| --- | --- | --- | --- | --- |
| 名称 | 是 | `tls` | `TLS_STANDARD_TAG` | TLS 列表可见 |
| 类型 | 是 | `TLS` | 固定值 | 类型显示为 TLS |
| 证书路径 | 是 | `/root/cert/<domain>/fullchain.pem` | `SSL_CERT_FULLCHAIN_PATH` | 文件存在 |
| 私钥路径 | 是 | `/root/cert/<domain>/privkey.pem` | `SSL_CERT_KEY_PATH` | 文件存在 |
| Server Name / SNI | 是 | `<domain>` | `TLS_STANDARD_SERVER_NAME` | 客户端连接成功 |
| ALPN | 是 | `h3,h2,http/1.1` | `TLS_STANDARD_ALPN` | TUIC/Trojan 可连 |
| 允许不安全 | 按策略 | 勾选 | `TLS_STANDARD_ALLOW_INSECURE` | 订阅链接含对应选项 |

需要勾选：

- TLS 启用。
- SNI 启用。
- ALPN 启用。
- 允许不安全按当前策略勾选。

### TLS 模板：Hysteria2 专用 TLS

| 字段 | 是否必填 | 面板填写值 | 自动化变量名 | 验证方式 |
| --- | --- | --- | --- | --- |
| 名称 | 是 | `hy2-tls` | `TLS_HYSTERIA2_TAG` | TLS 列表可见 |
| 类型 | 是 | `TLS` | 固定值 | 类型显示为 TLS |
| 证书路径 | 是 | `/root/cert/<domain>/fullchain.pem` | `SSL_CERT_FULLCHAIN_PATH` | 文件存在 |
| 私钥路径 | 是 | `/root/cert/<domain>/privkey.pem` | `SSL_CERT_KEY_PATH` | 文件存在 |
| Server Name / SNI | 是 | `<domain>` | `TLS_HYSTERIA2_SERVER_NAME` | Hysteria2 可连 |
| ALPN | 按需 | `h3` 或 S-UI 推荐默认 | `TLS_HYSTERIA2_ALPN` | Hysteria2 可连 |
| 允许不安全 | 按策略 | 勾选 | `TLS_HYSTERIA2_ALLOW_INSECURE` | 订阅链接含对应选项 |

Hysteria2 使用独立 TLS 模板，避免和 TUIC/Trojan 的 TLS 选项互相影响。

## 出站：住宅代理

| 字段 | 值 | 说明 |
| --- | --- | --- |
| 类型 | `socks` 或 `http` | 按服务商提供的协议填写 |
| Tag |  | 例如 `socks-residential` |
| 服务器 |  | 不要公开真实值 |
| 端口 |  |  |
| 用户名 |  | 不要公开真实值 |
| 密码 |  | 不要公开真实值 |
| 版本 | `5` | SOCKS5 时填写 |

填错影响：

- 服务器、端口、用户名、密码错误会导致节点能连上 VPS，但出口失败。
- 默认路由没有指向该 tag 时，目标网站可能看到 VPS IP，而不是住宅 IP。

## 节点：WireGuard / WARP Endpoint

| 字段 | 值 | 说明 |
| --- | --- | --- |
| 类型 | `wireguard` 或 `warp` | 面板节点管理里的类型 |
| Tag |  | 例如 `wireguard-5yp` |
| 私钥 |  | 不要公开真实值 |
| 公钥 |  | 对等端公钥 |
| 本地 IP 地址 |  | 例如 `10.0.0.186/32,fe80::ba/128` |
| 端口 |  | WireGuard 本地端口 |
| DNS 服务器 |  | 逗号分隔 |
| 对等体 |  | peer 配置 |
| 拨号 |  | dial 相关设置 |

填错影响：

- 私钥、公钥或 peer 参数错误会导致 endpoint 无法建立连接。
- endpoint tag 如果被路由或出站引用，改名会影响依赖它的配置。
- WireGuard/WARP endpoint 是服务器主动建立的网络端点，不是用户客户端连入 VPS 的入站。

## 客户端

| 字段 | 值 |
| --- | --- |
| 客户端名称 |  |
| 是否启用 |  |
| 流量限制 |  |
| 过期时间 |  |
| 绑定入站 |  |

## 入站：VLESS REALITY

| 字段 | 值 | 说明 |
| --- | --- | --- |
| 类型 | `vless` |  |
| Tag |  | 例如 `vless-reality` |
| 监听地址 | `::` | 同时覆盖 IPv4/IPv6 的常见写法 |
| 监听端口 | `443` | TCP |
| TLS 模板 | `reality` | 绑定前面创建的 REALITY 模板 |
| 握手目标 |  | 例如稳定 HTTPS 域名 |
| uTLS 指纹 | `chrome` |  |
| 传输 | `tcp` | 默认即可 |
| 绑定客户端 |  |  |
| 出站 | 默认路由或住宅出站 tag |  |

填错影响：

- Reality 密钥、short id、握手目标不匹配会导致客户端 TLS 握手失败。
- 端口未放行会导致客户端超时。

## 入站：TUIC

| 字段 | 值 | 说明 |
| --- | --- | --- |
| 类型 | `tuic` |  |
| Tag |  | 例如 `tuic-59501` |
| 监听地址 | `::` |  |
| 监听端口 | `59501` | UDP |
| 拥塞控制 | `bbr` |  |
| TLS 模板 | `tls` | 绑定普通 TLS 模板 |
| ALPN | `h3,h2,http/1.1` |  |
| 绑定客户端 |  |  |

填错影响：

- 只放行 TCP 不放行 UDP 会导致 TUIC 超时。
- 客户端不支持 TUIC 时，应使用其他入站。

## 入站：Hysteria2

| 字段 | 值 | 说明 |
| --- | --- | --- |
| 类型 | `hysteria2` |  |
| Tag |  | 例如 `hysteria2` |
| 监听地址 | `::` |  |
| 监听端口 |  | UDP，建议新手单独使用一个端口 |
| TLS 模板 | `hy2-tls` | 绑定 Hysteria2 专用 TLS 模板 |
| 绑定客户端 |  |  |

填错影响：

- UDP 端口未放行会导致连接失败。
- 和其他协议复用端口前必须确认 S-UI 和 sing-box 配置允许。

## 入站：Trojan WS/TLS

| 字段 | 值 | 说明 |
| --- | --- | --- |
| 类型 | `trojan` |  |
| Tag |  | 例如 `trojan-ws` |
| 监听地址 | `::` |  |
| 监听端口 | `41101` | TCP |
| TLS 模板 | `tls` | 绑定普通 TLS 模板 |
| 传输 | `WebSocket` |  |
| WebSocket 路径 |  | 长随机路径 |
| Host Header |  | 可填伪装域名 |
| 绑定客户端 |  |  |

填错影响：

- WebSocket 路径和客户端不一致会导致连接失败。
- TLS 证书错误会导致客户端拒绝连接。

## 端口冲突记录

| 端口 | 协议 | 使用方 | 是否冲突 | 处理 |
| --- | --- | --- | --- | --- |
| `443` | TCP |  |  |  |
| `443` | UDP |  |  |  |
| `2095` | TCP | Web 面板 |  |  |
| `2096` | TCP | 订阅 |  |  |
| `59501` | UDP | TUIC |  |  |
| `41101` | TCP | Trojan WS/TLS |  |  |
