# S-UI 验收记录模板

复制本文件到 `<workdir>/sites/<site-id>/generated/acceptance-YYYYMMDD.md` 后填写。真实记录默认不提交仓库。

## 基础信息

| 项目 | 值 |
| --- | --- |
| 验收日期 |  |
| 操作人 |  |
| VPS 公网 IP |  |
| 域名 |  |
| SSH 用户 |  |
| S-UI 版本 |  |
| 预期住宅出口 IP |  |

## 安全与凭据

| 验收项 | 结果 | 备注 |
| --- | --- | --- |
| SSH 可登录 |  |  |
| SSH 私钥权限为 `600` |  |  |
| root 密码已生成 |  |  |
| root 密码已保存到私密位置 |  |  |
| root 密码未提交仓库 |  |  |
| 未默认开启 SSH root 密码登录 |  |  |
| S-UI 默认密码已修改 |  |  |
| 面板路径为长随机路径 |  |  |
| 订阅路径为长随机路径 |  |  |

## 服务状态

| 验收项 | 命令 | 结果 |
| --- | --- | --- |
| `s-ui.service` active | `sudo systemctl is-active s-ui.service` |  |
| 数据库存在 | `sudo test -f /usr/local/s-ui/db/s-ui.db && echo ok` |  |
| 端口监听 | `sudo ss -lntup` |  |
| 最近日志无持续错误 | `sudo journalctl -u s-ui.service -n 50 --no-pager` |  |

## 面板与订阅

| 验收项 | 结果 | 备注 |
| --- | --- | --- |
| 面板 HTTPS 可打开 |  |  |
| 面板登录成功 |  |  |
| 订阅 HTTPS 可拉取 |  |  |
| 订阅链接未公开 |  |  |

## 节点导入与测速

| 节点 | 是否导入 | 是否连通 | 备注 |
| --- | --- | --- | --- |
| VLESS REALITY |  |  |  |
| TUIC |  |  |  |
| Hysteria2 |  |  |  |
| Trojan WS/TLS |  |  |  |

至少一个节点必须实际连通。

## 出口验证

| 验收项 | 结果 | 备注 |
| --- | --- | --- |
| `https://api.ipify.org` 显示住宅出口 IP |  |  |
| `https://ipinfo.io` 地区符合预期 |  |  |
| 目标网站未看到 VPS IP |  |  |
| DNS 泄漏检查已完成或记录为未检查 |  |  |
| WebRTC 泄漏检查已完成或记录为未检查 |  |  |
| QUIC 影响已检查或记录为未检查 |  |  |

## 备份

| 验收项 | 结果 | 备注 |
| --- | --- | --- |
| 已备份 `/usr/local/s-ui/` |  |  |
| 已备份 `/etc/systemd/system/s-ui.service` |  |  |
| 备份保存到私密位置 |  |  |
| 备份未提交仓库 |  |  |

## 脱敏确认

| 内容 | 是否已脱敏 |
| --- | --- |
| root 密码 |  |
| S-UI 管理员密码 |  |
| 订阅完整链接 |  |
| Reality 私钥和 short id |  |
| TLS 私钥 |  |
| 客户端 UUID 和密码 |  |
| Trojan 密码 |  |
| 住宅代理凭据 |  |
| 用户真实来源 IP |  |

## 结论

```text
通过 / 不通过：
剩余风险：
下一步：
```
