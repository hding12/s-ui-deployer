"""Safe .env parsing and config model helpers."""

from __future__ import annotations

from pathlib import Path


class ConfigError(ValueError):
    """Raised when a site env file is malformed or unsafe to parse."""


def load_env(path: str | Path) -> dict[str, str]:
    """Load a simple KEY=value env file without evaluating shell syntax.

    Supported forms:
    - KEY=value
    - KEY="value"
    - KEY='value'

    Unsupported forms intentionally raise ConfigError instead of trying to be
    shell-compatible. Real deployment config should be data, not executable
    shell.
    """

    env_path = Path(path)
    values: dict[str, str] = {}

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {env_path}") from exc

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            raise ConfigError(f"第 {line_no} 行不允许使用 export")
        if "=" not in line:
            raise ConfigError(f"第 {line_no} 行不是 KEY=value 格式")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key.isidentifier() or not key.isupper():
            raise ConfigError(f"第 {line_no} 行变量名不合法: {key}")
        if "$(" in value or "`" in value:
            raise ConfigError(f"第 {line_no} 行包含命令替换，已拒绝解析")
        if value.startswith(("'", '"')):
            quote = value[0]
            if not value.endswith(quote) or len(value) == 1:
                raise ConfigError(f"第 {line_no} 行引号不完整")
            value = value[1:-1]
        elif any(char.isspace() for char in value):
            raise ConfigError(f"第 {line_no} 行未加引号的值不能包含空白字符")

        values[key] = value

    return values
