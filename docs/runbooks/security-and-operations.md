# 安全与运维手册

本文档采用“密码为主”的安全策略：节点端口可以公网开放，主要依靠强密码、长随机路径、协议密钥和定期轮换降低风险。

这个策略方便新手快速搭建，但风险高于来源 IP 白名单。长期生产使用时，应尽量补充 IP 白名单、最小端口开放和告警。

## 1. 敏感信息分类

绝不能提交仓库：

- SSH 私钥。
- root 密码。
- S-UI 管理员密码。
- 面板完整登录地址。
- 订阅完整链接。
- 订阅 token。
- Reality private key、short id。
- TLS private key。
- 客户端 UUID 和密码。
- Trojan 密码。
- 住宅代理完整 URL、用户名、密码。
- s-ui 原始数据库备份。

可以提交仓库：

- 脱敏后的端口规划。
- 脱敏后的服务路径。
- 通用操作步骤。
- 空模板。
- 不含真实值的示例配置。

## 2. 密码生成规则

推荐用 1Password、系统密码管理器或等价工具生成并保存：

| 用途 | 建议 |
| --- | --- |
| root 密码 | 24 位以上随机密码 |
| S-UI 管理员密码 | 24 位以上随机密码 |
| 住宅代理密码 | 服务商提供或 24 位以上随机密码 |
| 面板路径 | 至少 16 字节随机字符串 |
| 订阅路径 | 至少 16 字节随机字符串 |
| WebSocket 路径 | 至少 16 字节随机字符串 |

如果使用 1Password CLI，后续自动化可以采用：

```text
生成强密码 -> 写入 1Password -> 将引用或一次性导出值写入 work/sites/<site-id>/site.env
```

不要把密码写进 `templates/config/env.example`。

## 3. Root 密码策略

AWS 默认通常使用普通用户，例如 `ubuntu`，再通过 `sudo` 执行管理员命令。为了后续自动化和恢复场景，可以为 root 设置强密码：

```bash
sudo passwd root
```

默认不启用 SSH root 密码登录。

不要默认修改：

```text
PermitRootLogin yes
PasswordAuthentication yes
```

如果必须临时开启，应记录原因、开启时间、关闭时间，并在操作后恢复关闭。

## 4. 端口开放策略

密码为主模型下，常见端口开放：

| 用途 | 协议 | 来源 |
| --- | --- | --- |
| SSH | TCP | 推荐只允许你的公网 IP |
| 面板 HTTPS | TCP | 可公网，但必须强密码和长路径 |
| 订阅 HTTPS | TCP | 可公网，但订阅路径必须保密 |
| VLESS REALITY | TCP | 可公网 |
| TUIC | UDP | 可公网 |
| Hysteria2 | UDP | 可公网 |
| Trojan WS/TLS | TCP | 可公网 |

安全组里 TCP 和 UDP 是不同规则。UDP 节点不通时，优先检查是否只放行了 TCP。

## 5. 最小防护清单

部署后立即完成：

- 修改 S-UI 默认管理员密码。
- 修改默认面板路径。
- 修改默认订阅路径。
- 使用 HTTPS 面板和 HTTPS 订阅。
- 为每个用户创建独立客户端。
- 住宅代理出站只保存在 S-UI 和本地私密配置中。
- 备份 `/usr/local/s-ui/db/s-ui.db`。
- 记录端口、域名、路径和节点类型，但不记录完整密钥。

每周检查：

- `s-ui.service` 是否 active。
- 端口是否仍按预期监听。
- 日志是否有异常来源、大量失败握手或爆破行为。
- 出口 IP 是否仍是预期住宅代理。
- 订阅链接是否出现在不该出现的地方。

## 6. 备份策略

建议在以下时点备份：

- 初次搭建完成。
- 修改面板路径或订阅路径前。
- 新增或删除入站前。
- 新增或删除客户端前。
- 轮换住宅代理凭据前。
- 升级 S-UI 前。
- 第一次安装 cert-supervisor 前（Timer 安装本身不危险，但验证过程依赖当前证书状态）。

备份命令：

```bash
sudo systemctl stop s-ui.service
sudo tar -czf /tmp/s-ui-backup-$(date +%Y%m%d-%H%M%S).tar.gz /usr/local/s-ui /etc/systemd/system/s-ui.service
sudo systemctl start s-ui.service
```

下载到本地：

```bash
scp -i /path/to/key.pem ubuntu@VPS_HOST:/tmp/s-ui-backup-YYYYMMDD-HHMMSS.tar.gz <workdir>/sites/<site-id>/backups/
```

`work/backups/` 默认不提交仓库。

## 7. 证书自动续签运维

证书自动续签采用 VPS 本机 systemd timer 内环 + 工作站监督外环的双层闭环。

### 7.1 安装

每个站点只需执行一次：

```bash
sui-deploy install-cert-supervisor <workdir>/sites/<site-id>/site.env
```

这会安装以下文件到 VPS：

| 文件 | 路径 | 作用 |
| --- | --- | --- |
| supervisor 脚本 | `/usr/local/s-ui-deployer/cert-supervisor.sh` | 单次检查+续签闭环 |
| supervisor 配置 | `/usr/local/s-ui-deployer/cert-supervisor.env` | 从 site.env 映射的环境变量 |
| systemd service | `/etc/systemd/system/sui-cert-supervisor.service` | 调用 supervisor 脚本 |
| systemd timer | `/etc/systemd/system/sui-cert-supervisor.timer` | 每 12 小时调度 |

状态和日志：

| 内容 | 路径 |
| --- | --- |
| 可机读状态 | `/var/lib/s-ui-deployer/cert-state.json` |
| 运行日志 | `/var/log/s-ui-deployer/cert-supervisor.log` |

### 7.2 日常巡检

```bash
# 检查证书状态（推荐每周）
sui-deploy cert-status <workdir>/sites/<site-id>/site.env

# 监督巡检（外环）
sui-deploy cert-supervise <workdir>/sites/<site-id>/site.env
```

`cert-supervise` 的退出码表示状态等级：

- 0：正常
- 2：降级（续签失败，但证书未到期）
- 3：紧急（剩余天数极少）
- 4：需人工介入（已过期或连续失败达上限）

### 7.3 手动续签

```bash
# 只预览操作
sui-deploy cert-renew <workdir>/sites/<site-id>/site.env --dry-run

# 实际执行
sui-deploy cert-renew <workdir>/sites/<site-id>/site.env
```

### 7.4 异常处理

如果自动续签反复失败：

1. 检查 DNS 解析：`sui-deploy cert-status <site.env>` 的 DNS 一致性字段
2. 检查 80 端口可达性：ACME HTTP challenge 需要 TCP 80 可达
3. 检查服务器时间：`sudo timedatectl` 确认无大幅漂移
4. 检查 S-UI 证书路径配置：`/root/cert/<domain>/fullchain.pem` 是否存在
5. 手动执行一次续签观察完整输出：`sui-deploy cert-renew <site.env>`
6. 如果连续失败超限进入 `manual_intervention`，检查远程日志：
   ```bash
   ssh -i <key> <user>@<host> "cat /var/log/s-ui-deployer/cert-supervisor.log"
   ```

## 9. 凭据轮换

触发轮换的情况：

- 订阅链接发错群。
- 面板地址被公开。
- 客户端设备丢失。
- 住宅代理服务商提示异常。
- 日志出现异常来源或大量失败尝试。
- 定期安全轮换。

轮换顺序：

1. 先备份 S-UI。
2. 禁用受影响客户端。
3. 重置客户端 UUID 或密码。
4. 必要时重置订阅路径。
5. 必要时重建 Reality/Trojan/TUIC/Hysteria2 密钥。
6. 必要时轮换住宅代理密码。
7. 重启 S-UI。
8. 重新导入客户端订阅并验证出口 IP。
9. 记录轮换时间和原因，不记录明文密码。

## 10. 泄露响应

如果怀疑订阅或节点被泄露：

1. 立即禁用受影响客户端。
2. 检查 `journalctl -u s-ui.service`，确认是否有陌生来源。
3. 重置订阅路径。
4. 重建受影响入站密钥或密码。
5. 重新生成客户端订阅。
6. 通知真实用户更新客户端。
7. 观察 24 小时日志。

如果怀疑 root 或 SSH 私钥泄露：

1. 立即在云控制台限制 SSH 来源。
2. 更换 SSH key。
3. 重置 root 密码。
4. 检查 `~/.ssh/authorized_keys`。
5. 检查系统新增用户和 crontab。
6. 必要时从干净备份重建 VPS。

## 11. 日志脱敏

以下命令可能输出域名、来源 IP、客户端标识和错误细节：

```bash
sudo journalctl -u s-ui.service -n 100 --no-pager
sudo ss -lntup
```

分享前删除：

- 完整订阅 URL。
- 密码、token、UUID。
- 住宅代理用户名和密码。
- 用户真实 IP。
- 业务访问域名，如果它属于隐私信息。

## 12. 合规边界

本文档只用于搭建受控、自用或授权用户使用的网络连接服务。不要把节点提供给未知用户，不要用于违反云厂商、住宅代理服务商或目标网站规则的用途。
