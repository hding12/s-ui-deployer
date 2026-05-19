# 链路级 CLI 扩展过渡路线图

本文档记录一个明确决策，以及当前实现状态：

- **当前阶段不做全局重构。**
- **当前阶段先采用“新增 CLI 扩展”的方式实现链路级管理。**
- **这次分析中发现的结构性问题不忽略，而是记入延期重构 TODO。**

这样做的目标是控制改动面，先把“新建一条链路、查看链路、删除链路”做成最小闭环，再决定是否进入更大范围的数据模型和执行引擎重构。

## 1. 当前阶段的目标

当前阶段只解决一个问题：

```text
在单个站点内，以 CLI 方式管理“完整链路”
```

这里的“完整链路”按当前约定定义为：

```text
一个用户 + 一个入站 + 一个出站策略 + 一条路由绑定
```

支持的出站策略：

- `direct`：不创建额外出站，走机器默认出口
- `shared`：复用现有出站
- `dedicated`：为该链路创建专属出站

## 2. 为什么现在先不做全局重构

当前仓库已经有一个可工作的站点级自动化闭环：

- `check`
- `diagnose`
- `bootstrap`
- `configure-panel`
- `issue-cert`
- `configure-https`
- `create-api-token`
- `api-export`
- `plan-apply`
- `apply`

如果现在立刻做全局重构，会同时触碰：

- `site.env` 数据边界
- `apply.py` 计划引擎
- CLI 结构
- 验证模型
- 测试模型

这会把“新增链路 CLI”从功能扩展变成底层重写，风险过大，回报周期过长。

因此本阶段采用更保守的策略：

- 保留现有站点级模型不动
- 在现有基础上新增链路级 CLI
- 把重构问题显式记账，后续按时机处理

## 3. 当前阶段建议范围

### 已实现命令

```bash
bin/sui-deploy chain-import-current <workdir>/sites/<site-id>/site.env
bin/sui-deploy chain-list <workdir>/sites/<site-id>/site.env
bin/sui-deploy chain-show <workdir>/sites/<site-id>/site.env <chain-id>
bin/sui-deploy chain-plan-create <workdir>/sites/<site-id>/site.env <chain.json>
bin/sui-deploy chain-apply-create <workdir>/sites/<site-id>/site.env <chain.json>
bin/sui-deploy chain-plan-delete <workdir>/sites/<site-id>/site.env <chain-id>
bin/sui-deploy chain-apply-delete <workdir>/sites/<site-id>/site.env <chain-id>
```

### 当前阶段仍可暂缓

```bash
bin/sui-deploy chain-plan-update ...
bin/sui-deploy chain-apply-update ...
bin/sui-deploy chain-verify ...
bin/sui-deploy chain-reconcile ...
```

## 4. 当前阶段的数据边界

当前阶段**不改** `site.env` 为全新结构，只新增一个链路目录：

```text
work/sites/<site-id>/
  site.env
  chains/
    <chain-id>.json
```

约束：

- `site.env` 继续保存站点级 SSH、域名、证书、TLS 默认参数、API token。
- `chains/*.json` 保存链路级用户、入站、出站和路由策略定义。
- 当前主链路通过 `chain-import-current` 从现有站点导入，避免面板状态和本地定义脱节。

## 5. 当前阶段的实现策略

### 5.1 不重写 `apply.py`

当前阶段不把现有 `plan-apply/apply` 拆成通用执行引擎。

做法：

- 新建链路级 workflow 模块
- 复用现有：
  - `/apiv2/load`
  - `/apiv2/clients?id=...`
  - `/apiv2/save`
  - `backup`
  - `restartSb`

### 5.2 不改变现有站点级命令语义

当前站点级命令继续只负责：

- 建站
- 面板配置
- 证书
- 站点主拓扑初始化

链路级命令只负责：

- 新增链路
- 删除链路
- 读取链路视图

### 5.3 先做“最小验证”

当前阶段链路创建成功的最小判据：

- client 已创建
- inbound 已创建
- route rule 已创建
- outbound 已存在或已创建
- 链路 links 已生成
- 目标监听端口存在

当前阶段先不强制自动验证真实出口 IP。

### 5.4 当前实现状态

当前已经实现：

- `chain-import-current`
- `chain-list`
- `chain-show`
- `chain-plan-create`
- `chain-apply-create`
- `chain-plan-delete`
- `chain-apply-delete`

当前行为边界：

- `chain-import-current` 优先按 route rule 导入当前主链路；如果命中了 route rule，导入结果一律标记为 `shared`，不自动推断 dedicated ownership。
- `chain-plan-create` / `chain-apply-create` 会在真正写远端前做前置校验。以下情况按致命错误直接阻断：
  - 端口被其他 tag 占用
  - TLS 模板不存在
  - `shared` 模式引用的出站不存在
- `chain-apply-create` 只在前置校验通过后才执行远端备份。
- `chain-apply-delete` 只会在链路定义明确为 `dedicated`，且没有其他链路引用该出站时才删除出站。
- 当前验证仍然偏向结构验证，不自动做真实出口 IP 和协议级连通性验证。

## 6. 延期重构 TODO

以下问题已经确认存在，但当前阶段不立即处理：

### TODO-1：`site.env` 混合了站点全局配置和主链路配置

现状：

- `OUTBOUND_*`
- `INBOUND_*`
- `CLIENT_NAME`

这些字段本质上属于“单条链路”，但现在被塞在站点级配置里。

风险：

- 多链路扩展时边界不清
- 站点定义和链路定义耦合

后续方向：

- 站点级配置与链路级配置彻底拆分

### TODO-2：`apply.py` 仍是固定拓扑收敛器

现状：

- 固定 3 个 TLS
- 固定 4 个入站
- 固定 1 个客户端
- 出站只支持全局 `route.final`

风险：

- 不适合多链路增量管理
- 难以支持通用对象 CRUD

后续方向：

- 拆成通用对象计划器 + 通用执行器 + 链路级编排器

### TODO-3：CLI 结构仍然是扁平命令

现状：

- 所有命令都平铺在顶层

风险：

- 随着 `chain-*`、`cert-*`、`site-*` 增多会失控

后续方向：

- 重构为命令命名空间，例如：
  - `site ...`
  - `chain ...`
  - `cert ...`

### TODO-4：路由规则缺少 ownership 模型

现状：

- 当前工具还没有稳定的“链路归属规则”标识

风险：

- 删除链路时可能误删他人规则
- 无法安全做 reconcile

后续方向：

- 设计规则命名规范、注释字段或等价 ownership 标记

### TODO-5：共享出站缺少引用计数与托管标记

现状：

- 共享出站和专属出站没有被清晰区分

风险：

- 删除链路时误删共享出站

后续方向：

- 增加 outbound ownership / refcount 模型

### TODO-6：并发漂移控制缺失

现状：

- CLI 执行时无法确认面板是否被人工并发修改

风险：

- apply 结果不收敛
- 本地链路定义与远端状态漂移

后续方向：

- 引入 snapshot hash、乐观锁或 reconcile 机制

### TODO-7：真实链路输出验证还不完整

现状：

- 当前更偏向结构验证

风险：

- “对象存在”不等于“链路可用”

后续方向：

- 增加出口 IP 验证
- 增加协议级连通校验

## 7. 什么情况下必须进入全局重构

当出现以下任一条件时，应停止继续堆增量 CLI，转入全局重构：

1. 一个站点要长期维护多条链路，并频繁更新。
2. 出现多个共享出站、多个专属出站、多个入站并存的复杂路由关系。
3. 需要稳定支持 `update`、`reconcile`、`drift detect`。
4. 需要多人共同维护同一站点。
5. 当前链路级 CLI 出现大量重复代码，开始复刻 `apply.py` 逻辑。

## 8. 当前阶段的验收标准

采用 CLI 扩展方案后，本阶段当前应满足：

- 能从现有站点导入当前主链路
- 能列出链路清单
- 能查看单条链路详情
- 能创建 `direct` / `shared` / `dedicated` 三类链路
- 能删除链路且不误删共享出站
- 每次写操作前自动备份
- 每次写操作后执行结构验证，并在失败时返回非零退出码

## 9. 决策结论

这份路线图的核心不是“拒绝重构”，而是：

- **先用新增 CLI 扩展交付链路能力**
- **同时把结构债明确记录在案**
- **等功能最小闭环跑通后，再决定何时进入全局重构**
