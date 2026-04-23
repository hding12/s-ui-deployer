# 站点工作目录样例

这个目录是一个可提交到源码仓库的“站点配置样例”。它不包含任何真实 IP、域名、密码、token、代理凭据或 SSH 私钥。

使用方式：

```bash
export SUI_WORKDIR="$HOME/s-ui-deployer-work"
export SITE_ID="example-site"

mkdir -p "$SUI_WORKDIR/sites/$SITE_ID"
cp examples/site-workspace-template/site.env.example "$SUI_WORKDIR/sites/$SITE_ID/site.env"
mkdir -p "$SUI_WORKDIR/sites/$SITE_ID"/{logs,backups,generated,api-export}
```

然后编辑：

```text
$SUI_WORKDIR/sites/$SITE_ID/site.env
```

填写原则：

- `SITE_ID` 使用站点名称，例如 `example-us-1`、`example-eu-1`、`example-asia-1`。
- 自动化创建的主客户端名称默认使用 `SITE_ID`。
- SSH 私钥可以放在任意本机路径；工具会自动修正权限为 `600`。
- 真实密码、token、住宅代理凭据只能写入工作目录下的真实 `site.env`，不要写进源码仓库。
- `SUI_API_TOKEN` 初始可以留空，运行 `create-api-token` 后工具会写回真实 `site.env`。
