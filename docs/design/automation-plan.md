# 自动化改造计划

本文档规划如何把 S-UI 搭建流程逐步自动化。当前已经落地 `source/` / `work/` 目录边界、CLI 骨架、只读诊断、安装、证书、HTTPS 配置、API token 创建、API 导出、`plan-apply` 和 `apply` 的首版闭环。

## 设计原则

- 先做只读诊断，再做半自动部署。
- 所有真实配置和动态数据放在 `work/`，默认不提交仓库。
- 自动化必须先备份，再修改。
- 不直接把真实密码写进模板。
- 不默认开启 SSH root 密码登录。
- 不在首版直接写 s-ui 数据库，除非已有备份、回滚和版本兼容检查。
- 不假设 S-UI 原生支持跨多台 EC2 的中心化管理；多实例管理由本工具作为外部编排层完成。
- 首版只支持 Ubuntu/Debian。

## Phase 1：本地配置与检查清单

目标：让新手先把信息填完整。

产物：

- `templates/config/env.example`
- `source/docs/templates/setup-checklist.md`
- `source/docs/templates/node-config-template.md`
- `source/docs/templates/acceptance-record-template.md`

后续可增加命令：

```bash
bin/sui-deploy check <workdir>/sites/<site-id>/site.env
bin/sui-deploy generate-passwords --provider 1password
bin/sui-deploy render-checklist <workdir>/sites/<site-id>/site.env
```

检查项：

- 配置文件权限不宽于 `600`。
- `VPS_HOST`、`SSH_USER`、`SSH_KEY_PATH` 非空。
- `ROOT_PASSWORD` 不为空，或 `ROOT_PASSWORD_SOURCE` 指向可解析的密码管理器引用。
- `WEB_PATH`、`SUB_PATH` 是长随机路径。
- 入站端口合法，且 TCP/UDP 协议标注清晰。
- 出站代理字段非空。

## Phase 2：SSH 只读诊断

目标：不修改 VPS，只确认服务器状态。

后续命令：

```bash
bin/sui-deploy diagnose <workdir>/sites/<site-id>/site.env
```

诊断内容：

- SSH 是否可登录。
- 当前用户是否可 sudo。
- 系统版本和架构。
- root 密码是否已设置，能否通过 `su -` 验证由人工完成。
- `s-ui` 命令是否存在。
- `s-ui.service` 是否存在并 active。
- `/usr/local/s-ui/db/s-ui.db` 是否存在。
- 面板端口、订阅端口、节点端口是否监听。
- UFW 状态。

输出位置：

```text
work/logs/diagnose-YYYYMMDD-HHMMSS.log
work/generated/instance-summary-YYYYMMDD-HHMMSS.md
```

生成的摘要必须脱敏。

## Phase 3：半自动安装

目标：对干净 Ubuntu/Debian VPS 执行基础安装。

后续命令：

```bash
bin/sui-deploy bootstrap <workdir>/sites/<site-id>/site.env
```

阶段：

1. 本地配置检查。
2. SSH 连通性检查。
3. 远端系统检查。
4. 设置 root 密码。
5. 安装依赖。
6. 安装 S-UI，并在 `Do you want to continue with the modification [y/n]?` 提示处输入 `n`。
7. 捕获安装输出，解析初始管理员用户名和密码。
8. 检查 `s-ui.service`。
9. 验证初始面板可登录。
10. 开启 BBR。
11. 输出下一步面板手工配置提示。

Root 密码处理：

- `ROOT_PASSWORD_SOURCE=manual`：从 `work/sites/<site-id>/site.env` 读取 `ROOT_PASSWORD`。
- `ROOT_PASSWORD_SOURCE=1password`：通过 `op` 读取或生成密码。
- `ROOT_PASSWORD_SOURCE=generated`：本地生成密码，写入 `work/shared/secrets/`，并提示用户转存到密码管理器。

默认行为：

- 设置 root 密码。
- 不启用 SSH root 密码登录。
- 不修改 `sshd_config` 的 `PermitRootLogin`。
- 不修改 `PasswordAuthentication`。
- AWS 机器默认按 UFW inactive 处理，主要检查 AWS Security Group。
- 安装日志保存到 `work/logs/`，解析出的初始管理员信息只写入私密配置或密码管理器。

SSL 证书自动化规则：

- 申请前确认域名解析到 VPS 公网 IP。
- 申请前确认 AWS Security Group 开放 `80/tcp`。
- 使用 S-UI 菜单申请证书时，自动化必须显式输入 `80`。S-UI v1.4.1 的提示写着可直接回车使用默认 `80`，但实测空输入可能导致端口为空并失败。
- 证书生成后验证 `/root/cert/<domain>/fullchain.pem` 和 `/root/cert/<domain>/privkey.pem` 存在。
- 不把 `/root/.acme.sh/<domain>_ecc/<domain>.cer` 和 `<domain>.key` 写入 S-UI 面板配置。它们是 acme.sh 签发/续签工作目录；S-UI 脚本会通过 `acme.sh --installcert` 安装到 `/root/cert/<domain>/fullchain.pem` 和 `privkey.pem`，这才是面板、订阅和 TLS 模板的标准使用路径。
- 只保存证书路径，不保存私钥内容。

## Phase 4：备份、恢复与脱敏摘要

目标：让任何修改前都有可回滚状态。

已实现命令：

```bash
bin/sui-deploy backup <workdir>/sites/<site-id>/site.env
```

后续命令：

```bash
bin/sui-deploy summarize <workdir>/backups/s-ui-backup.tar.gz
bin/sui-deploy restore <workdir>/sites/<site-id>/site.env <workdir>/backups/s-ui-backup.tar.gz
```

备份范围：

```text
/usr/local/s-ui/
/usr/local/s-ui/db/s-ui.db
/usr/local/s-ui/db/s-ui.db-wal
/usr/local/s-ui/db/s-ui.db-shm
/etc/systemd/system/s-ui.service
```

备份文件保存在：

```text
work/backups/
```

脱敏摘要只输出：

- s-ui 版本。
- 服务状态。
- 面板域名、端口、路径摘要。
- 订阅域名、端口、路径摘要。
- 入站数量、类型、端口、tag。
- 出站数量、类型、tag。
- 路由 final tag。

不输出：

- 密码。
- token。
- 私钥。
- UUID。
- 住宅代理完整凭据。

## Phase 5：S-UI API 配置自动化

目标：使用 S-UI token API 自动创建出站、TLS、入站、客户端和订阅设置。

依据：

- S-UI 官方支持 `/apiv2` token API。
- `GET /apiv2/load` 可导出完整面板对象。
- `POST /apiv2/save` 可保存 `clients`、`tls`、`endpoints`、`inbounds`、`outbounds`、`config`、`settings` 等对象。
- `GET /apiv2/getdb` 可下载数据库备份。
- `POST /apiv2/restartSb` 可重启 sing-box core。
- `GET /apiv2/keypairs?k=reality|tls|wireguard` 可生成 keypair，减少解析面板输出。

推荐拆分：

```text
Phase 5A：API 只读导出和脱敏模板生成
Phase 5B：API 创建/编辑节点、出站、TLS、客户端
Phase 5C：API 创建/编辑入站和订阅设置
Phase 5D：只在 API 覆盖不足时评估数据库写入
```

实现顺序：

1. 自动备份。
2. 读取 `/apiv2/load`。
3. 从参考实例导出 payload 模板。
4. 脱敏并参数化模板。
5. 渲染新实例 payload。
6. 调用 `/apiv2/save`。
7. 调用 `/apiv2/restartSb`。
8. 读取 `/apiv2/status`、`/apiv2/logs` 和 `/apiv2/load` 验证。

进入 Phase 5 前必须具备：

- API token 创建和保存流程。
- S-UI 版本检查。
- 干跑模式。
- 配置 diff。
- 回滚命令。
- 在测试 VPS 上验证。

已实现命令：

```bash
bin/sui-deploy api-export <workdir>/sites/<site-id>/site.env
bin/sui-deploy plan-apply <workdir>/sites/<site-id>/site.env
bin/sui-deploy apply <workdir>/sites/<site-id>/site.env
```

`plan-apply` 当前行为：

- 读取 `/apiv2/load`。
- 使用 `/apiv2/keypairs?k=reality` 生成 REALITY 公私钥。
- 生成原始计划到 `work/sites/<site-id>/generated/plan-apply.raw.json`。
- 生成脱敏计划到 `work/sites/<site-id>/generated/plan-apply.redacted.json`。
- 不修改远端配置。

`apply` 当前行为：

- 读取计划文件；不存在时现场生成。
- 先执行 `backup`。
- 依次调用 `/apiv2/save` 创建或编辑 TLS、出站、config、客户端和入站。
- 已存在对象按 name/tag 转为 `edit`，避免重复创建。
- 调用 API 重启 sing-box core。
- 读取 `/apiv2/load` 并写入脱敏结果。

后续命令：

```bash
bin/sui-deploy rollback <workdir>/sites/<site-id>/site.env <workdir>/backups/last-known-good.tar.gz
```

首批可自动化对象：

- WireGuard/WARP endpoint 节点。
- REALITY、普通 TLS、Hysteria2 专用 TLS 模板。
- 住宅 SOCKS 出站。
- 默认路由 final 出站。
- VLESS REALITY 入站。
- TUIC 入站。
- Hysteria2 入站。
- Trojan WS/TLS 入站。
- 单个客户端和订阅。

当前首版仍不做：

- 不直接写 SQLite 数据库。
- 不自动创建 AWS EC2 或修改 AWS Security Group。
- 不自动做客户端真实连通测速。

已从“不做”移出的能力：

- API token 创建已经通过 Web API 自动化，并写入 `work/sites/<site-id>/site.env`。
- 管理员账号密码已经可通过 CLI 自动配置。
- 节点配置已通过 `/apiv2/save` 自动创建，不再需要人工面板逐项填写。

更多细节见 [api-automation-evaluation.md](api-automation-evaluation.md)。

## Phase 6：多 EC2 外部编排

目标：在多台 AWS EC2 上分别运行独立 S-UI 实例，由 `s-ui-deployer` 统一读取 inventory 并批量调用 SSH 和 `/apiv2`。

推荐目录：

```text
work/sites/
  example-site-1.env
  example-site-2.env
  aws-tokyo-1.env
```

每个 `.env` 代表一台 EC2，包含：

- `INSTANCE_NAME`
- `VPS_HOST`
- `SSH_USER`
- `SSH_KEY_PATH`
- `DOMAIN`
- `SUI_API_BASE_URL`
- `SUI_API_TOKEN` 或 token 来源
- 实例专属端口、路径、出站和客户端配置

后续命令：

```bash
bin/sui-deploy diagnose-all <workdir>/sites/
bin/sui-deploy backup-all <workdir>/sites/
bin/sui-deploy apply-nodes-all <workdir>/sites/
bin/sui-deploy report-all <workdir>/sites/
```

实现原则：

- 每台 EC2 独立备份、独立写入、独立回滚。
- 默认串行执行批量写操作，降低同时误配置的影响面。
- 诊断和只读报告可以并发。
- 每台 EC2 固定 S-UI 版本模板，避免跨版本 payload 混用。
- 聚合报告只能保存脱敏摘要。
- 如果要生成聚合订阅，输出到 `work/generated/`，不提交仓库。

## 验收标准

每个自动化阶段都必须满足：

- 可以重复执行。
- 不打印明文密码。
- 失败时说明失败阶段。
- 修改前创建备份。
- 日志写入 `work/logs/`。
- 输出用户可读的下一步建议。

## 不做的事情

首版不做：

- 不购买或销毁云服务器。
- 不管理云安全组 API。
- 不实现多云 provider。
- 不维护用户计费系统。
- 不维护代理池。
- 不自动绕过第三方平台风控。
- 不把密码上传到除用户明确选择的密码管理器以外的服务。
