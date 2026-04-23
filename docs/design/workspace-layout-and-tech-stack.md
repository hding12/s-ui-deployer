# S-UI Deployer Workspace 目录与技术栈规划

## 目录边界

推荐把源码仓库和运行态工作目录分开：

```text
s-ui-deployer/          # git 仓库：工具源码、模板、文档、测试
s-ui-deployer-work/     # 本机工作目录：真实站点配置、日志、备份、生成物
```

`s-ui-deployer/` 是 git 仓库主体。它应该能被复制到另一台机器上继续开发，而不会带走任何真实密码、私钥、订阅链接或备份数据库。

`s-ui-deployer-work/` 是本机私密工作目录。不同 EC2 站点都放在 `<workdir>/sites/<site-id>/`，避免把真实站点配置散落在源码目录中。

## 工作目录模型

每台 EC2 使用一个站点目录：

```text
<workdir>/sites/example-site/
  site.env
  README.md
  logs/
  backups/
  generated/
  api-export/
```

`site.env` 保存该站点真实配置，例如：

```bash
SITE_ID="example-site"
VPS_HOST="203.0.113.10"
SSH_USER="ubuntu"
SSH_KEY_PATH="<workdir>/shared/ssh-keys/example.pem"
DOMAIN="panel.example.com"
SUI_API_BASE_URL="https://panel.example.com:2095/app"
```

跨站点复用但仍敏感的内容放在：

```text
<workdir>/shared/secrets/
<workdir>/shared/ssh-keys/
```

这样可以同时满足两个目标：

- 多台 EC2 的配置彼此隔离，便于单独诊断、备份和验收。
- SSH 私钥、密码引用和代理凭据可以复用，但不会进入源码仓库。

## 源码目录设计原理

```text
bin/
src/sui_deployer/
templates/
docs/
examples/
tests/
```

`bin/` 只放命令入口，例如 `sui-deploy`。入口脚本只负责定位 Python 包并调用 CLI，不放业务逻辑。

`src/sui_deployer/` 放真正的工具逻辑。模块按职责拆分：

- `config.py`：安全解析 `.env`，拒绝命令替换、多行值和危险写法。
- `validate.py`：校验端口、路径、TLS tag、占位值和源码目录误放真实配置。
- `ssh.py`：封装 OpenSSH/scp 调用。
- `remote.py`：渲染并执行远端 shell 模板。
- `parser.py`：解析 S-UI 安装输出、管理员信息、证书路径和诊断输出。
- `sui_api.py`：封装 `/apiv2` 登录、读取、保存和 keypair 生成。
- `render.py`：渲染 JSON payload、脱敏 diff 和验收记录。
- `secrets.py`：处理本地随机密码生成、1Password 引用和敏感字段脱敏。

`workflow/` 放用户能感知的一组流程，例如：

- `diagnose`：只读 SSH 诊断。
- `bootstrap`：安装依赖、安装 S-UI、解析初始管理员信息。
- `cert`：通过 S-UI CLI/acme 流程申请证书并校验证书路径。
- `backup`：备份数据库、证书和服务文件。
- `api_export`：读取 S-UI API 并生成脱敏导出。
- `apply`：先备份，再通过 API 创建 TLS、出站、客户端和入站。

`templates/payloads/s-ui-v1.4.1/` 按 S-UI 版本隔离 payload，避免把 v1.4.1 的字段误用于未来版本。

`templates/remote/` 放上传到 VPS 执行的 shell 模板。远端脚本保持薄，只做系统命令，例如 `apt`、`systemctl`、`ss`、`tar`、证书申请；复杂判断留在 Python 里，便于测试。

`docs/` 和源码同仓库管理，确保手册、设计和工具行为同步更新。

`examples/` 只放可提交的示例配置，所有敏感字段必须为空或占位。

`tests/` 首先覆盖配置解析、输出解析、payload 渲染和敏感信息扫描。真实 SSH/API 操作不作为默认单元测试执行。

## 技术栈结论

推荐技术栈：

```text
Python 3 标准库优先 + OpenSSH/scp + 少量远端 Bash + S-UI /apiv2
```

结论：这是当前阶段通用、简洁、合理的选择。

## 为什么选 Python 3

Python 适合处理本项目的核心任务：

- 安全解析 `.env`。
- 渲染 JSON payload。
- 调用 HTTP API。
- 解析安装输出和诊断日志。
- 生成脱敏报告。
- 写单元测试覆盖关键边界。

v1 优先使用标准库，减少安装依赖。后续如果确实需要更好的 SSH 控制或模板能力，再评估 `paramiko`、`jinja2` 等依赖。

## 为什么保留 OpenSSH/scp

SSH/scp 是 VPS 部署的通用基础设施。直接调用本机 OpenSSH 有几个优点：

- 用户已经有 `.pem` 私钥和 SSH 登录经验。
- 不需要先在 Python 里实现完整 SSH 协议。
- 便于复用 `~/.ssh/config`、known_hosts、代理跳板等现有能力。
- 后续如果 EC2 数量增加，可以把执行层替换为 Ansible，而不影响上层 workflow。

## 为什么只用少量远端 Bash

远端 Bash 适合做系统操作：

- 安装包。
- 启动和检查 `s-ui.service`。
- 申请证书。
- 检查端口监听。
- 打包备份文件。

但 Bash 不适合承载复杂业务逻辑。`.env` 解析、JSON 渲染、API 响应处理、敏感字段脱敏都放在 Python 中，避免脚本变脆。

## 为什么不首选纯 Bash

纯 Bash 会在这些地方变复杂：

- 安全解析 `.env`，避免误执行 `$(...)` 或反引号。
- 可靠生成 JSON payload。
- 处理 API 错误和结构化响应。
- 做多 EC2 inventory。
- 写可维护的单元测试。

所以 Bash 只作为远端系统操作的薄层。

## 为什么不首选 Ansible

Ansible 对新手和小规模部署偏重。当前项目的关键动作不是传统包管理，而是 S-UI 面板 API 编排、payload 渲染、证书路径记录和订阅验证。

等站点数量增加后，可以把 `ssh.py` / `remote.py` 替换或扩展为 Ansible 执行层，但 v1 不需要先引入。

## 为什么不首选 Terraform/OpenTofu

当前目标是在已有 AWS EC2 上部署和管理 S-UI，不负责创建、销毁或变更云资源生命周期。AWS Security Group 自动化也暂不纳入 v1。

过早引入 IaC 会把云资源生命周期和 S-UI 配置自动化混在一起，增加新手理解成本。

## 为什么不首选 Node.js

Node.js 也能实现，但本项目没有前端构建需求。Python 在运维脚本、日志解析、JSON 处理和本地 CLI 场景下更直接，目标用户也更容易在 VPS/运维语境下接受 Python + shell。

## v1 技术边界

v1 不做这些事：

- 不引入数据库。
- 不引入 Web UI。
- 不引入 Celery/队列。
- 不引入 Terraform。
- 不直接写 S-UI SQLite。
- 不自动创建 AWS EC2。
- 不自动修改 AWS Security Group。

v1 优先完成最小闭环：

```text
check -> diagnose -> bootstrap -> issue-cert -> api-export -> plan-apply -> apply
```

其中 `check`、`diagnose`、`api-export`、`plan-apply` 优先实现为只读或不改远端的低风险命令；`bootstrap`、`issue-cert`、`apply` 再逐步实现，并且所有可写操作必须写日志、先备份、默认脱敏输出。
