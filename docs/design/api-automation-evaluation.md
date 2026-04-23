# S-UI API 自动化评估

评估日期：2026-04-22

结论：S-UI 已开放 API，后续可以把当前通过面板完成的节点、入站、出站、TLS、客户端、订阅和核心配置管理逐步自动化。建议不要直接写 SQLite 数据库作为首选方案，而是优先使用 S-UI 官方的 token API `/apiv2`。

补充结论：S-UI 不提供原生跨多台 AWS EC2 的中心化集群管理。官方功能中的 `Multi-Client/Inbound` 是指单个 S-UI 实例内可管理多个客户端和多个入站，不是一个面板统一管理多台远端 S-UI 服务器。

## 1. 依据

官方资料显示 S-UI 支持两套 API：

- `/api`：前端面板使用的接口，依赖登录 session 和 cookie。
- `/apiv2`：面向外部程序的 REST API，使用 `Token` 请求头鉴权。

官方 Wiki 文档说明 `/apiv2` token 需要在 Admin 页面创建，并在请求头中传入：

```bash
curl -H "Token: <Your Token Key>" "http://localhost:2095/app/apiv2/inbounds?id=2"
```

官方 README 也明确列出 S-UI 支持 `API Interface`，默认面板端口、路径、订阅端口和订阅路径分别是 `2095`、`/app/`、`2096`、`/sub/`。

v1.4.1 源码确认：

- `/apiv2` 的路由会先检查 `Token` 请求头。
- `GET /apiv2/load` 可加载完整配置数据。
- `GET /apiv2/endpoints`、`inbounds`、`outbounds`、`tls`、`clients`、`settings`、`config` 等可读取分项数据。
- `POST /apiv2/save` 统一保存配置对象。
- `POST /apiv2/restartSb` 可重启 sing-box core。
- `GET /apiv2/getdb` 可下载数据库备份。

参考链接：

- https://github.com/alireza0/s-ui/wiki/API-Documentation
- https://github.com/alireza0/s-ui
- https://github.com/alireza0/s-ui/blob/v1.4.1/api/apiV2Handler.go
- https://github.com/alireza0/s-ui/blob/v1.4.1/api/apiService.go
- https://github.com/alireza0/s-ui/blob/v1.4.1/service/config.go

## 2. 当前面板操作与 API 覆盖关系

| 面板操作 | API 支持情况 | 推荐自动化方式 |
| --- | --- | --- |
| 节点管理 | 支持 | `POST /apiv2/save`，`object=endpoints` |
| 入站管理 | 支持 | `POST /apiv2/save`，`object=inbounds` |
| 出站管理 | 支持 | `POST /apiv2/save`，`object=outbounds` |
| TLS 管理 | 支持 | `POST /apiv2/save`，`object=tls` |
| 客户端/节点用户管理 | 支持 | `POST /apiv2/save`，`object=clients` |
| 面板设置、订阅域名、订阅端口、订阅路径 | 支持 | `POST /apiv2/save`，`object=settings` |
| sing-box 基础配置和默认路由 | 支持 | `POST /apiv2/save`，`object=config` |
| 订阅链接读取 | 支持 | `GET /apiv2/load` 返回 `subURI`，客户端对象包含 links |
| 数据库备份下载 | 支持 | `GET /apiv2/getdb` |
| 重启 sing-box core | 支持 | `POST /apiv2/restartSb` |
| 重启 S-UI 面板 | 支持 | `POST /apiv2/restartApp` |
| API token 创建 | 不由 `/apiv2` 自举 | 首次仍建议在 Admin 页面手工创建 token |
| 管理员账号改密 | `/api` 支持，`/apiv2` 不作为主路径 | 首次仍建议面板手工完成 |

这里的“用户”按 S-UI 面板里的客户端/节点用户理解。如果指 S-UI 管理员账号，自动化能力更弱，首次引导仍应手工处理。

### 节点管理和入站管理的区别

S-UI 面板里的“节点管理”不是“客户端订阅节点”的泛称，而是 sing-box 的 `endpoint` 配置管理。你在添加节点界面看到的 WireGuard 字段，例如私钥、公钥、本地 IP、端口、DNS 服务器、对等体、拨号，对应的就是 WireGuard endpoint。

S-UI 源码中：

- 节点管理对应 `EndpointService`。
- 数据库存储在 `endpoints` 表。
- API 对象名是 `endpoints`。
- 保存时会调用 sing-box runtime 的 `AddEndpoint` 或 `RemoveEndpoint`。
- `warp` 类型会在输出 sing-box 配置时转换为 `wireguard`。

入站管理则对应 sing-box 的 `inbounds`：

- 管理对外监听端口。
- 接收客户端连接。
- 常见类型包括 VLESS、Trojan、TUIC、Hysteria2、SOCKS、HTTP。
- API 对象名是 `inbounds`。
- 数据库存储在 `inbounds` 表。

两者的关系：

```text
endpoint 节点 = 服务器主动拨出去或建立虚拟网络端点，例如 WireGuard/WARP
inbound 入站 = 服务器对用户开放的入口，例如 VLESS/Trojan/TUIC/Hysteria2
outbound 出站 = 服务器访问外部网络的出口，例如 SOCKS/HTTP/direct
```

因此后续自动化必须把“节点管理”单独建模为 `endpoints`，不能把它混同为 `inbounds` 或客户端订阅节点。

## 2.1 多 EC2 管理能力判断

S-UI 当前更像“单机面板 + 本机 sing-box core”：

- 安装文档默认把 S-UI、数据库和 sing-box core 放在同一台机器。
- 数据目录是本机路径，例如 `/usr/local/s-ui/db/s-ui.db`。
- API 操作的是当前 S-UI 实例里的本地对象。
- `restartSb` 重启的是当前实例的 sing-box core。
- `status`、`logs`、`getdb` 读取的是当前实例状态、日志和数据库。

未发现原生能力：

- 多 AWS EC2 inventory。
- 中央控制面板登记多个远端 S-UI 实例。
- 跨实例批量发布配置。
- 跨实例健康检查聚合。
- 跨实例订阅统一聚合。
- 跨实例故障转移或集群状态同步。
- 原生 provider adapter，例如 AWS EC2 创建、销毁、安全组管理。

因此，跨多 EC2 自动化应由外部编排层完成，而不是期望单个 S-UI 面板直接管理所有机器。

推荐架构：

```text
本地/控制端 s-ui-deployer
  -> 读取 inventory/env
  -> SSH/API 操作 EC2-A 上的 S-UI
  -> SSH/API 操作 EC2-B 上的 S-UI
  -> SSH/API 操作 EC2-C 上的 S-UI
  -> 生成统一验收报告和可选聚合订阅
```

每台 EC2 仍运行独立 S-UI 实例、独立数据库、独立 API token。`s-ui-deployer` 负责批量部署、批量备份、批量诊断和批量套模板。

## 3. `/apiv2/save` 行为

`POST /apiv2/save` 使用表单字段：

```text
object=<对象类型>
action=<动作>
data=<JSON 字符串>
initUsers=<可选，创建入站时初始化绑定的客户端 id 列表>
```

源码中 `object` 支持：

- `clients`
- `tls`
- `inbounds`
- `outbounds`
- `services`
- `endpoints`
- `config`
- `settings`

常见 `action`：

- `new`
- `edit`
- `del`

`clients` 额外支持：

- `addbulk`
- `editbulk`
- `delbulk`

对象保存后，S-UI 会写入变更记录，并在部分对象变化时更新客户端链接、入站 out_json 或重启对应 sing-box 入站/出站。相比直接改数据库，API 路径能复用 S-UI 自己的校验、链接生成和运行时更新逻辑。

## 4. 推荐的自动化策略

首版不要手写复杂协议 JSON。推荐使用“面板导出模板 + API 回放”的方式：

1. 人工在一台参考实例上通过面板创建 WireGuard/WARP 节点、VLESS REALITY、TUIC、Hysteria2、Trojan、住宅 SOCKS 出站、TLS、客户端和订阅设置。
2. 创建短期 API token。
3. 调用 `GET /apiv2/load` 导出完整对象。
4. 脱敏后保存为 `work/generated/s-ui-api-template.redacted.json`。
5. 从导出对象中抽取可参数化字段，例如域名、端口、路径、tag、上游代理、客户端名称。
6. 用模板渲染新实例 payload。
7. 调用 `POST /apiv2/save` 按顺序创建对象。
8. 调用 `POST /apiv2/restartSb` 重启 core。
9. 调用 `GET /apiv2/load` 和 `GET /apiv2/status` 验证结果。

推荐顺序：

```text
settings -> tls -> endpoints -> outbounds -> config(route final) -> clients -> inbounds -> restartSb -> load/status/checkOutbound
```

原因：

- 入站可能引用 TLS。
- 路由或拨号规则可能引用 endpoint tag。
- 客户端链接生成依赖入站和 hostname。
- 默认路由依赖出站 tag。
- 订阅地址依赖 settings。

## 5. Token 和访问方式

首次 token 推荐手工创建：

1. 登录 S-UI 面板。
2. 进入 Admin 页面。
3. 创建 API Token。
4. 设置过期时间。
5. 复制 token 到 1Password 或 `work/shared/secrets/`。

本地配置建议新增字段：

```bash
SUI_API_BASE_URL="https://panel.example.com:2095/app"
SUI_API_TOKEN=""
SUI_API_TOKEN_SOURCE="manual"
```

请求示例：

```bash
curl -fsS \
  -H "Token: $SUI_API_TOKEN" \
  "$SUI_API_BASE_URL/apiv2/load"
```

保存示例：

```bash
curl -fsS \
  -H "Token: $SUI_API_TOKEN" \
  -X POST \
  --data-urlencode "object=outbounds" \
  --data-urlencode "action=new" \
  --data-urlencode "data@payload-outbound.json" \
  "$SUI_API_BASE_URL/apiv2/save"
```

注意：S-UI 源码使用 `FormValue` 读取字段，所以首版脚本应使用 `application/x-www-form-urlencoded` 或 multipart/form-data，而不是直接发送裸 JSON。

## 6. 能自动化到什么程度

适合自动化：

- 读取当前完整配置。
- 备份数据库。
- 创建和编辑出站。
- 创建和编辑 endpoint 节点，例如 WireGuard/WARP。
- 创建和编辑 TLS 配置。
- 创建和编辑入站。
- 创建和编辑客户端。
- 设置订阅端口、订阅路径、订阅域名等 settings。
- 设置默认路由和基础 config。
- 重启 core。
- 读取订阅 URI、客户端链接和服务状态。
- 检查出站是否可用。
- 生成 REALITY、TLS、WireGuard keypair。

暂不建议自动化：

- 首次管理员密码修改。
- 首次 API token 创建。
- 直接修改 SQLite 数据库。
- 未经模板验证直接生成复杂协议 payload。
- 跨 S-UI 大版本复用 payload。

可优先用 API 替代终端解析的动作：

```text
GET /apiv2/keypairs?k=reality
GET /apiv2/keypairs?k=tls&o=<serverName>
GET /apiv2/keypairs?k=wireguard
POST /apiv2/save object=tls
POST /apiv2/save object=inbounds
POST /apiv2/save object=outbounds
POST /apiv2/save object=clients
POST /apiv2/save object=config
POST /apiv2/save object=settings
```

仍需要 CLI 或输出解析的动作：

- 首次安装时解析初始管理员 `username:` 和 `password:`。
- 如果安装输出丢失，用 `/usr/local/s-ui/sui admin -show` 兜底读取。
- S-UI 菜单申请 SSL 证书当前主要走 `s-ui.sh` + `acme.sh`，自动化应验证固定文件路径存在，而不是只信终端文本。

解析规则：

- 能用 API、CLI 状态命令或固定文件路径验证时，不只依赖终端输出。
- 解析终端输出后，必须执行实际连接或文件存在性验证。
- 解析到的管理员密码、证书路径、token 只能写入 `work/sites/<site-id>/site.env` 或密码管理器。

## 7. 风险与防护

主要风险：

- 官方 API 文档仍标注为进行中，payload 细节不完整。
- 不同 S-UI 版本的对象字段可能变化。
- API token 权限较高，泄露后可修改配置。
- 错误 payload 可能导致 sing-box core 启动失败。
- `settings` 或 `config` 保存错误可能导致面板、订阅或节点不可用。

防护要求：

- 每次 `save` 前先调用 `GET /apiv2/getdb` 备份。
- 每次 `save` 后立即调用 `GET /apiv2/status` 或 `GET /apiv2/logs`。
- 使用短期 token，定期轮换。
- token 放入 `work/shared/secrets/` 或密码管理器，不提交仓库。
- 每次自动化操作写入 `work/logs/`。
- 输出 payload diff，首轮变更人工确认。
- 按 S-UI 版本固定模板，例如 `templates/api/v1.4.1/`。

## 8. 对自动化计划的调整

原计划 Phase 5 中“可选 API/数据库自动配置节点”应改为：

```text
Phase 5A：API 只读导出和脱敏模板生成
Phase 5B：API 创建/编辑节点、出站、TLS、客户端
Phase 5C：API 创建/编辑入站和订阅设置
Phase 5D：只在 API 覆盖不足时评估数据库写入
```

数据库写入应降级为最后手段，不作为首选实现。

## 9. 多 EC2 自动化建议

如果要管理多台 AWS EC2，建议在 `s-ui-deployer` 增加外部 inventory，而不是改造单个 S-UI 面板：

```text
work/sites/
  example-site-1.env
  example-site-2.env
  aws-tokyo-1.env
```

每个实例配置独立保存：

```bash
INSTANCE_NAME="example-site-1"
VPS_HOST="203.0.113.10"
SSH_USER="ubuntu"
SSH_KEY_PATH="/path/to/key.pem"
DOMAIN="panel-1.example.com"
SUI_API_BASE_URL="https://panel-1.example.com:2095/app"
SUI_API_TOKEN=""
```

后续命令形态：

```bash
bin/sui-deploy diagnose-all <workdir>/sites/
bin/sui-deploy backup-all <workdir>/sites/
bin/sui-deploy apply-nodes-all <workdir>/sites/
bin/sui-deploy report-all <workdir>/sites/
```

多实例输出：

- 每台 EC2 的服务状态。
- 每台 EC2 的入站、出站、TLS、客户端数量。
- 每台 EC2 的出口 IP。
- 每台 EC2 的 API token 到期时间。
- 每台 EC2 的最近备份时间。
- 可选生成一个聚合订阅文件，放在 `work/generated/`，但不公开真实订阅链接。

不建议：

- 多台 S-UI 共用同一个 SQLite 数据库。
- 多台 S-UI 共用同一个 API token。
- 用一台 S-UI 直接覆盖另一台 S-UI 的数据库。
- 在没有版本检查和备份的情况下跨实例批量写配置。
