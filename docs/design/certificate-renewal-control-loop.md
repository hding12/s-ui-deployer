# 证书自动更新控制方案

本文为 S-UI Deployer 设计一套面向生产使用的证书自动更新方案。目标不是“能续签一次”，而是建立一个可观测、可判定、可执行、可回退、可扩展的闭环控制系统。

## 1. 设计背景

截至 `2026-05-18`，Let's Encrypt 仍广泛签发 `90` 天证书；官方同时在 `2026-02-24` 公布了 `45` 天证书推进计划。因此，这套方案不能把“90 天有效期、提前 30 天续签”写死在代码里，而应根据证书实际有效期动态计算续签窗口。

当前项目中，S-UI 申请证书的首发路径已经明确：

- 签发/续签工作目录：`/root/.acme.sh/<domain>_ecc/`
- 面板、订阅、TLS 模板实际使用路径：`/root/cert/<domain>/fullchain.pem` 与 `privkey.pem`

这意味着自动更新的核心不只是“acme.sh 成功”，还必须同时保证：

1. `/root/cert/<domain>/` 下的目标证书已更新。
2. S-UI 服务重新加载了新证书。
3. 面板、订阅和相关 TLS 入口对外已经提供新证书。

## 2. 按工程控制论拆解系统

按钱学森工程控制论的思路，系统分成 6 个基本要素：

1. **被控对象**
   - 远端 VPS 上的证书文件、S-UI 面板、S-UI core、TLS 模板绑定关系。

2. **控制目标**
   - 任意时刻证书都处于有效状态。
   - 续签过程不依赖人工盯守。
   - 证书更新后，外部可观测服务已经切换到新证书。
   - 出现异常时能在证书过期前多次重试，并保留回退证据。

3. **观测器**
   - 远端证书文件解析。
   - 远端服务状态与监听状态。
   - 外部 TLS 握手返回的实际证书。
   - S-UI API / settings / TLS 配置一致性。

4. **控制器**
   - 根据剩余有效期、最近一次续签结果、失败次数和一致性检查结果，决定：
     - 继续观察
     - 进入续签窗口
     - 立即续签
     - 进入告警/人工介入状态

5. **执行器**
   - `acme.sh --renew`
   - `acme.sh --install-cert`
   - `systemctl restart s-ui.service`
   - 必要时 `configure-https` 做设置重对齐

6. **反馈回路**
   - 每次动作后都重新观测证书文件、服务状态和外部 TLS 握手。
   - 只有“新证书已生成 + 新证书已安装 + 服务已加载 + 外部握手正确”全部满足，才判定续签成功。

## 3. 三种方案与取舍

### 方案 A：只依赖 acme.sh 自带 cron

做法：

- 使用 S-UI 菜单完成首次签发。
- 之后完全依赖 acme.sh 自带 cron/定时任务自动续签。

优点：

- 实现最简单。
- 改动最少。

缺点：

- 看不见实际状态。
- 无法确认 `/root/cert/<domain>/` 是否确实被重新安装。
- 无法确认 S-UI 是否已加载新证书。
- 出问题时通常只在证书即将过期或已经过期后才被发现。

结论：不推荐作为生产方案。

### 方案 B：本地续签 + 本工具做监督闭环

做法：

- 仍然使用 acme.sh 作为证书签发和续签执行器。
- 在 VPS 上安装一个轻量监督器，通过 `systemd timer` 定时：
  - 检查证书剩余寿命
  - 触发续签
  - 重新安装到 `/root/cert/<domain>/`
  - 重启 `s-ui.service`
  - 校验证书已被服务加载
- 本地 `S-UI Deployer` 作为外层编排器，负责安装、巡检、汇总和跨站点管理。

优点：

- 控制回路靠近被控对象，工作站离线时也能续签。
- 保留现有技术栈：`Python + SSH + acme.sh + systemd`
- 适合单站点和多站点。

缺点：

- 需要新增远端脚本和 timer。
- 需要定义状态文件和日志规范。

结论：**推荐方案。**

### 方案 C：完全由本地工作站集中续签

做法：

- 不在 VPS 上安装 timer。
- 由本机或管理机定时执行 `sui-deploy cert-supervise <site.env>`。

优点：

- 所有控制逻辑集中在本地源码仓库。

缺点：

- 管理机必须持续在线。
- 本地网络、VPN、DNS 或关机都会影响续签。
- 不符合“控制器尽量贴近被控对象”的工程原则。

结论：只适合作为补充巡检，不适合作为主回路。

## 4. 推荐的分层闭环

推荐采用“两层控制”：

### 内环：站点本机自保持控制

部署在 VPS 上，负责高频、自动、自治运行：

- 定时检查证书状态。
- 判断是否进入续签窗口。
- 调用 acme.sh 续签。
- 安装证书到 `/root/cert/<domain>/`。
- 重启 `s-ui.service`。
- 做本机验证。
- 记录日志和状态。

### 外环：S-UI Deployer 监督控制

部署在工作站或管理机，负责低频、跨站点、汇总式监督：

- 拉取站点证书状态。
- 检查最近一次自动续签结果。
- 检查失败次数是否持续增加。
- 检查外部 TLS 握手是否与预期一致。
- 给出人工处理指令或后续编排动作。

这样做的好处是：

- 内环保证自动性。
- 外环保证可见性和跨站点一致性。
- 即使外环短期离线，内环也不会停摆。

## 5. 控制目标与判定指标

### 5.1 控制目标

对每个站点，必须同时满足：

- 证书未过期。
- 证书主题/SAN 包含 `DOMAIN`。
- `/root/cert/<domain>/fullchain.pem` 和 `privkey.pem` 存在且可读。
- `s-ui.service` 为 `active`。
- `WEB_PORT` 与 `SUB_PORT` 的 TLS 握手成功。
- 如果存在基于同一证书的 TCP TLS 入口，例如 Trojan `41101/tcp`，则该入口也能返回新证书。

### 5.2 核心观测量

- `not_before`
- `not_after`
- `days_remaining`
- `cert_fingerprint_sha256`
- `served_fingerprint_sha256`（2095/2096/41101）
- `service_active`
- `dns_expected_ip == resolved_ip`
- `last_renew_attempt_at`
- `last_renew_success_at`
- `consecutive_failures`
- `last_error_code`

## 6. 续签窗口的动态计算

不要把阈值写死成“30 天前续签”。推荐按证书实际寿命计算：

- `lifetime_days = not_after - not_before`
- `renew_before_days = ceil(lifetime_days / 3)`
- `urgent_before_days = max(3, ceil(lifetime_days / 6))`

因此：

- 对 `90` 天证书：
  - 进入续签窗口：剩余 `30` 天
  - 进入紧急窗口：剩余 `15` 天

- 对 `45` 天证书：
  - 进入续签窗口：剩余 `15` 天
  - 进入紧急窗口：剩余 `8` 天左右

同时允许人工覆盖：

- `CERT_RENEW_BEFORE_DAYS`
- `CERT_RENEW_URGENT_BEFORE_DAYS`

如果配置了覆盖值，则以配置为准。

## 7. 自动更新状态机

建议采用显式状态机：

### `healthy`

- 剩余时间大于续签窗口。
- 最近验证通过。
- 只观察，不动作。

### `renew_due`

- 剩余时间进入续签窗口。
- 执行续签流程。

### `verifying`

- 续签命令已完成。
- 正在验证证书文件、服务重启和外部握手。

### `degraded`

- 本次续签失败，但证书尚未到期。
- 等待退避后重试。

### `urgent`

- 剩余时间进入紧急窗口。
- 提高重试频率，并触发更强告警。

### `manual_intervention`

- 证书已过期，或连续失败次数达到上限。
- 自动化停止重复折腾，保留现场，等待人工处理。

## 8. 执行流程

### 8.1 观测

每次调度先做只读检查：

1. 解析本地证书文件：
   - `openssl x509 -in fullchain.pem -noout -subject -issuer -dates -fingerprint -sha256`
2. 校验 `DOMAIN` 与 SAN/主题一致。
3. 校验 DNS 解析到 `VPS_HOST`。
4. 校验 `s-ui.service` 处于 `active`。
5. 通过 `openssl s_client` 或等价方式验证：
   - `DOMAIN:WEB_PORT`
   - `DOMAIN:SUB_PORT`
   - 可选：`DOMAIN:INBOUND_TROJAN_PORT`

### 8.2 判定

- 若 `days_remaining > renew_before_days`，退出。
- 若 `days_remaining <= renew_before_days`，进入续签。
- 若连续失败且 `days_remaining <= urgent_before_days`，进入紧急重试。

### 8.3 续签

推荐执行器改为直接调用 acme.sh，而不是重复走 S-UI 交互菜单：

```bash
/root/.acme.sh/acme.sh --renew -d "$DOMAIN" --ecc --home /root/.acme.sh
```

无论 acme.sh 是否自动安装，都显式执行一次安装步骤，确保 `/root/cert/<domain>/` 同步：

```bash
/root/.acme.sh/acme.sh --install-cert -d "$DOMAIN" --ecc \
  --fullchain-file "$SSL_CERT_FULLCHAIN_PATH" \
  --key-file "$SSL_CERT_KEY_PATH"
```

然后统一重载：

```bash
systemctl restart s-ui.service
```

这里推荐直接重启 `s-ui.service`，而不是只调用 `api/restartApp` 或 `apiv2/restartSb`。原因是新证书同时服务于：

- Web 面板
- 订阅服务
- 依赖 TLS 模板的节点入口

使用 systemd 统一重启更直接，也更符合“单一执行器驱动整个被控对象”的原则。

### 8.4 验证

续签后必须全部通过才算成功：

1. 新证书文件存在。
2. `not_after` 晚于旧证书。
3. `s-ui.service` 已恢复 `active`。
4. `WEB_PORT` TLS 握手返回的新指纹与本地证书一致。
5. `SUB_PORT` TLS 握手返回的新指纹与本地证书一致。
6. 可选：`INBOUND_TROJAN_PORT` 也返回新指纹。

## 9. 回退与异常处理

### 9.1 回退原则

证书续签前必须保存旧版本证书文件：

```text
/root/cert/<domain>/fullchain.pem
/root/cert/<domain>/privkey.pem
```

建议额外复制到：

```text
/root/cert/<domain>/backup-YYYYMMDD-HHMMSS/
```

如果续签后验证失败：

1. 恢复备份文件。
2. `systemctl restart s-ui.service`
3. 标记为 `degraded` 或 `manual_intervention`
4. 输出错误码和日志路径

### 9.2 常见扰动与应对

- **DNS 漂移**
  - 现象：域名不再解析到 `VPS_HOST`
  - 处理：不执行续签，直接告警

- **80 端口被占用**
  - 现象：standalone challenge 无法绑定 `80`
  - 处理：先检测端口占用；必要时短暂停止冲突进程或改用替代 challenge

- **80 端口外部不通**
  - 现象：acme challenge 失败
  - 处理：记录为外部依赖失败，提升到人工处理

- **服务器时间漂移**
  - 现象：证书校验异常
  - 处理：校验 `timedatectl`，必要时先修时钟

- **S-UI 设置漂移**
  - 现象：settings 里指向了错误证书路径
  - 处理：调用 `configure-https` 做重对齐

- **服务重启失败**
  - 现象：证书已更新，但面板或 core 没起来
  - 处理：立即回退证书并重启；进入人工介入

## 10. 运行频率

### 本机内环

推荐：

- 正常检查频率：每 `12` 小时一次
- 紧急窗口重试频率：每 `30` 分钟一次
- 单次续签失败后退避：`30` 分钟、`2` 小时、`6` 小时

### 外环监督

推荐：

- 每天一次汇总站点证书状态
- 每周一次人工抽查若干站点的真实 TLS 握手与面板可达性

## 11. 详细实施计划

下面这部分不再停留在“应该做什么”，而是明确写成开发实施顺序、模块边界、命令契约和验收标准。

### 11.1 实施范围

本轮只交付证书闭环，不顺手做这些事情：

- 不改现有 `bootstrap`、`issue-cert` 的主流程语义。
- 不改 `apply`、`chain-*` 命令。
- 不引入消息队列、数据库或 Web UI。
- 不把多站点批量监督和单站点续签实现绑在一起。

本轮必须交付：

```bash
bin/sui-deploy cert-status <site.env>
bin/sui-deploy cert-renew <site.env>
bin/sui-deploy cert-supervise <site.env>
bin/sui-deploy install-cert-supervisor <site.env>
```

可选附加命令：

```bash
bin/sui-deploy cert-tail-log <site.env>
```

### 11.2 模块与文件落点

建议新增或修改以下文件：

```text
src/sui_deployer/workflow/cert.py
templates/remote/cert-supervisor.sh.tpl
templates/remote/sui-cert-supervisor.service.tpl
templates/remote/sui-cert-supervisor.timer.tpl
templates/config/env.example
src/sui_deployer/cli.py
tests/test_cert.py
```

职责拆分：

- `workflow/cert.py`
  - 本地命令入口
  - SSH 调用
  - 状态解析
  - 结果判定
  - 本地日志与生成物输出

- `cert-supervisor.sh.tpl`
  - 远端单次监督器
  - 只负责一个站点、一次闭环
  - 负责观测、判定、执行、验证、写状态

- `service/timer.tpl`
  - 只负责调度，不放业务逻辑

- `tests/test_cert.py`
  - 阈值计算
  - 状态机迁移
  - 指纹比对
  - 退出码
  - 结果解析

### 11.3 远端落地布局

推荐远端目录：

```text
/usr/local/s-ui-deployer/
  cert-supervisor.sh
  cert-supervisor.env

/var/lib/s-ui-deployer/
  cert-state.json

/var/log/s-ui-deployer/
  cert-supervisor.log
  cert-renew-YYYYMMDD-HHMMSS.log

/etc/systemd/system/
  sui-cert-supervisor.service
  sui-cert-supervisor.timer
```

控制含义：

- `/usr/local/s-ui-deployer/`：执行器和静态配置
- `/var/lib/s-ui-deployer/`：可机读状态
- `/var/log/s-ui-deployer/`：可追溯日志
- `systemd`：调度器

这样可以把“配置”“状态”“日志”三者隔离，避免后续排障时混在一起。

### 11.4 本地工作目录落点

本地工作目录只保存脱敏摘要和运行记录，不缓存远端私钥内容：

```text
work/sites/<site-id>/generated/cert-status.json
work/sites/<site-id>/generated/cert-renew-YYYYMMDD-HHMMSS.json
work/sites/<site-id>/generated/cert-supervise-YYYYMMDD-HHMMSS.json
work/sites/<site-id>/logs/cert-renew-YYYYMMDD-HHMMSS.log
work/sites/<site-id>/logs/cert-supervise-YYYYMMDD-HHMMSS.log
```

### 11.5 配置字段

建议在 `site.env` 中增加以下字段：

```bash
CERT_AUTORENEW_ENABLED="true"
CERT_RENEW_METHOD="acme.sh"
CERT_RENEW_BEFORE_DAYS=""
CERT_RENEW_URGENT_BEFORE_DAYS=""
CERT_MAX_CONSECUTIVE_FAILURES="5"
CERT_RETRY_BACKOFF_MINUTES="60"
CERT_SUPERVISOR_INTERVAL="12h"
CERT_STATE_DIR="/var/lib/s-ui-deployer"
CERT_LOG_DIR="/var/log/s-ui-deployer"
CERT_RELOAD_STRATEGY="restart_s_ui"
CERT_VERIFY_EXTRA_PORTS="41101"
```

字段规则：

- `CERT_RENEW_BEFORE_DAYS`、`CERT_RENEW_URGENT_BEFORE_DAYS` 留空时按证书寿命动态计算。
- `CERT_SUPERVISOR_INTERVAL` 只控制 timer 调度频率，不直接决定紧急状态下的重试频率。
- `CERT_VERIFY_EXTRA_PORTS` 允许附加验证 Trojan 等共用证书的 TLS 入口。
- 动态运行状态不写回 `site.env`。

### 11.6 状态文件模型

远端状态文件必须稳定、可解析、可审计。建议结构：

```json
{
  "domain": "panel.example.com",
  "cert_path": "/root/cert/panel.example.com/fullchain.pem",
  "key_path": "/root/cert/panel.example.com/privkey.pem",
  "not_before": "2026-05-01T00:00:00Z",
  "not_after": "2026-07-30T23:59:59Z",
  "lifetime_days": 90,
  "days_remaining": 72,
  "renew_before_days": 30,
  "urgent_before_days": 15,
  "state": "healthy",
  "service_active": true,
  "dns_matches_expected": true,
  "file_fingerprint_sha256": "sha256:...",
  "served_fingerprint_sha256": {
    "2095": "sha256:...",
    "2096": "sha256:...",
    "41101": "sha256:..."
  },
  "last_check_at": "2026-05-19T10:00:00Z",
  "last_renew_attempt_at": "2026-05-10T02:00:00Z",
  "last_renew_success_at": "2026-05-10T02:01:20Z",
  "consecutive_failures": 0,
  "last_error_code": "",
  "last_error_message": ""
}
```

这个状态文件就是控制论中的“观测量快照”。内环和外环都以它为准，而不是互相猜测。

### 11.7 命令契约

#### `cert-status`

职责：

- SSH 读取远端 `cert-state.json`
- 如果状态文件不存在，则做一次即时只读探测
- 输出脱敏状态摘要

返回语义：

- `0`：状态可读，且当前不处于失败状态
- `1`：状态不可读或探测失败
- `2`：状态可读，但已处于 `degraded` / `urgent` / `manual_intervention`

#### `cert-renew`

职责：

- 手动触发一次完整续签闭环
- 不是只跑 `acme.sh`
- 必须包含备份、安装、重启、验证、状态写回

支持参数：

- `--dry-run`
- `--force`

返回语义：

- `0`：成功
- `1`：前置检查失败或执行失败
- `2`：执行了续签，但验证失败

#### `cert-supervise`

职责：

- 读取状态
- 根据状态机判断是否需要执行续签
- 可选地调用远端 supervisor
- 输出等级化结果

返回语义建议：

- `0`：healthy / renew_due 但无需人工处理
- `2`：degraded
- `3`：urgent
- `4`：manual_intervention

#### `install-cert-supervisor`

职责：

- 上传远端脚本、env、systemd 单元文件
- `daemon-reload`
- `enable --now` timer
- 立即触发一次首次检查
- 拉回状态验证安装结果

返回语义：

- `0`：安装成功
- `1`：上传、启用或首次检查失败

### 11.8 远端 supervisor 单次执行流程

远端脚本一次执行必须严格按这个顺序：

1. 读取配置
2. 观测当前证书、DNS、服务、外部握手
3. 计算 `lifetime_days`、`renew_before_days`、`urgent_before_days`
4. 根据状态机判断：
   - 仅观测退出
   - 进入续签
   - 进入紧急重试
   - 进入人工介入
5. 如果要续签：
   - 备份当前 `/root/cert/<domain>/`
   - 执行 `acme.sh --renew`
   - 显式执行 `acme.sh --install-cert`
   - 重启 `s-ui.service`
   - 再次观测
   - 校验文件证书和对外服务证书一致
6. 写状态文件
7. 写日志
8. 返回退出码

任何一步失败，都不能跳过最终状态写回。

### 11.9 状态机与退避策略

状态机规则：

- `healthy`
  - `days_remaining > renew_before_days`
  - 服务与握手都正常

- `renew_due`
  - `days_remaining <= renew_before_days`
  - 执行一次续签

- `verifying`
  - 续签动作已完成
  - 正在做文件与握手验证

- `degraded`
  - 本次续签失败
  - 证书尚未到期
  - 连续失败次数未超上限

- `urgent`
  - `days_remaining <= urgent_before_days`
  - 或剩余寿命极低时仍未恢复健康

- `manual_intervention`
  - 证书已过期
  - 或连续失败次数达到 `CERT_MAX_CONSECUTIVE_FAILURES`

退避策略：

- `degraded`
  - 若距离上次失败小于 `CERT_RETRY_BACKOFF_MINUTES`，只观测不重试
- `urgent`
  - 可以忽略普通退避，允许更频繁重试
- `manual_intervention`
  - 停止自动折腾，保留现场

### 11.10 成功与失败判据

续签成功必须同时满足：

1. `/root/cert/<domain>/fullchain.pem` 存在
2. `/root/cert/<domain>/privkey.pem` 存在
3. 新证书 `not_after` 晚于旧证书
4. `s-ui.service` 为 `active`
5. `WEB_PORT` TLS 握手证书指纹等于文件证书指纹
6. `SUB_PORT` TLS 握手证书指纹等于文件证书指纹
7. `CERT_VERIFY_EXTRA_PORTS` 中的端口如启用，也返回相同指纹

只要有一项不满足，就不能判成功。

### 11.11 失败处置

失败时遵循“先止损、再记录、后人工”的原则：

1. 保留原始日志
2. 保留旧证书备份目录
3. 写 `last_error_code` 与 `last_error_message`
4. 必要时恢复备份证书并重启 `s-ui.service`
5. 不自动重写面板配置，除非明确判断为证书路径漂移

### 11.12 开发里程碑

#### Iteration 1：只读观测

交付：

- `cert-status`
- 远端即时探测逻辑
- 状态文件结构
- 单元测试

验收：

- 能读取证书、服务、指纹、剩余天数
- 不修改远端

#### Iteration 2：单次人工续签

交付：

- `cert-renew --dry-run`
- `cert-renew`
- 远端 supervisor 首版

验收：

- 能手动跑通一次完整续签闭环
- 成功/失败退出码明确

#### Iteration 3：远端自动调度

交付：

- `install-cert-supervisor`
- `systemd service/timer`
- 远端状态与日志落盘

验收：

- 工作站离线时，VPS 仍可自治巡检与续签

#### Iteration 4：外环监督

交付：

- `cert-supervise`
- 状态等级与本地归档

验收：

- 能区分 `healthy`、`degraded`、`urgent`、`manual_intervention`

#### Iteration 5：文档与收尾

交付：

- README 更新
- 工具部署手册更新
- 运维手册更新
- 故障处理章节

### 11.13 测试矩阵

单元测试至少覆盖：

- 动态阈值计算
- 状态机迁移
- 证书时间解析
- 指纹比对
- 多端口验证汇总
- 连续失败计数
- 退避逻辑
- 退出码

集成测试至少覆盖：

1. 未到续签窗口，仅观测
2. 到续签窗口，续签成功
3. DNS 解析错误
4. `80/tcp` 未开放
5. `s-ui.service` 重启失败
6. 文件已更新，但对外握手未切新证书
7. `WEB_PORT` 正常、`SUB_PORT` 异常
8. 连续失败进入 `manual_intervention`

### 11.14 验收标准

只有同时满足下面这些，才算闭环完成：

- `install-cert-supervisor` 可重复执行且幂等
- `cert-status` 能稳定输出当前证书状态
- `cert-renew` 能在测试站点完整跑通
- `cert-supervise` 能按状态等级返回非零退出码
- 远端 timer 在工作站离线时仍可运行
- 续签成功后，对外 TLS 指纹与文件证书一致
- 所有日志和状态默认脱敏
- 失败不会静默通过

## 15. 方案结论

推荐结论很明确：

- **不要只依赖 acme.sh 自带 cron。**
- **使用“远端本机内环 + 本地工具外环”的双层闭环。**
- **续签动作改用非交互 acme.sh 命令，而不是长期依赖 S-UI 菜单交互。**
- **验证以“外部 TLS 握手是否已切到新证书”为最终判据，而不是只看终端输出。**
- **所有阈值按证书实际寿命动态计算，避免在 Let's Encrypt 生命周期缩短后失效。**

## 参考依据

- Let's Encrypt 官方关于 `45` 天证书推进与续签窗口说明：
  - https://letsencrypt.org/2026/02/24/rate-limits-45-day-certs
- Let's Encrypt 官方集成建议，推荐在证书生命周期剩余约三分之一时自动续签：
  - https://letsencrypt.org/docs/integration-guide/
- acme.sh 官方文档，`--install-cert`、自动续签与安装参数持久化：
  - https://github.com/acmesh-official/acme.sh
  - https://github.com/acmesh-official/acme.sh/wiki/How-to-install
