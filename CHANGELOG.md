# Changelog

本项目当前采用 Keep a Changelog 风格记录版本变化。

## [v0.1.0] - 2026-05-20

### Added

- 新增链路级 CLI：
  - `chain-import-current`
  - `chain-list`
  - `chain-show`
  - `chain-plan-create`
  - `chain-apply-create`
  - `chain-plan-delete`
  - `chain-apply-delete`
- 新增证书自动续签闭环命令：
  - `cert-status`
  - `cert-renew`
  - `cert-supervise`
  - `install-cert-supervisor`
- 新增链路数据模型和工作目录 `chains/` 约定。
- 新增证书自动续签状态机、远端 `systemd timer` 监督器、状态文件模型和外环巡检逻辑。
- 新增链路 CLI 与证书续签相关单元测试。
- 新增设计文档：
  - `docs/design/chain-cli-extension-roadmap.md`
  - `docs/design/certificate-renewal-control-loop.md`

### Changed

- README、工具部署手册、安全运维手册和自动化路线图已更新到当前工具能力。
- `install-cert-supervisor` 安装流程现在包含首次实际检查，并要求状态文件成功生成后才判定安装完成。
- `cert-status` / `cert-supervise` 现在把服务状态、DNS 一致性和 TLS 指纹一致性纳入状态判定，不再只按证书剩余天数给出结论。
- `cert-renew` / 远端 supervisor 现在把 TLS 握手失败视为验证失败，而不是静默通过。

### Fixed

- 修复 `cert` 工作流中的多个闭环问题：
  - `sudo` 环境变量传递导致的远端安装失败
  - 证书指纹解析与本地状态构建不一致
  - `dry-run`、`--force`、`skip_reason=not_due` 的控制流问题
  - 远端状态文件时间戳和观测量被错误覆盖
  - `CERT_VERIFY_EXTRA_PORTS` 未参与 probe 导致的持续误报
- 修复 `chain-plan-create` 的计划输出变量错误。

### Verified

- 已在真实站点 `aws-jp1` 上完成现场验证：
  - `cert-status` 正常，证书状态为 `healthy`
  - `install-cert-supervisor` 成功，首次检查通过
  - 新用户 `jp1-user-d` 已创建
  - `18443/tcp`、`18444/tcp` 两个 `VLESS + REALITY` 入站已生效
  - 两条新路由规则均指向独立出站 `socks-jp1-user-d`
