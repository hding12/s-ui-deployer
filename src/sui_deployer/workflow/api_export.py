"""S-UI API export workflow."""

from __future__ import annotations

import json
from pathlib import Path

from sui_deployer.sui_api import SuiApiV2, web_base_url


def run(values: dict[str, str], config_path: str) -> int:
    token = values.get("SUI_API_TOKEN", "")
    if not token:
        print("ERROR: SUI_API_TOKEN 为空，请先运行 create-api-token")
        return 1

    output_dir = Path(config_path).parent / "api-export"
    output_dir.mkdir(parents=True, exist_ok=True)

    verify_tls = values.get("SUI_API_TLS_VERIFY", "true").lower() == "true"
    api = SuiApiV2(
        web_base_url(values, scheme="https", host=values["DOMAIN"]),
        token=token,
        resolve_ip=values.get("VPS_HOST"),
        verify_tls=verify_tls,
    )

    try:
        response = api.get("apiv2/load")
    except Exception as exc:
        print(f"ERROR: /apiv2/load 导出失败: {exc}")
        return 1

    if not response.get("success"):
        print(f"ERROR: /apiv2/load 返回失败: {response.get('msg')}")
        return 1

    raw_path = output_dir / "load.raw.json"
    summary_path = output_dir / "load.summary.json"
    raw_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    obj = response.get("obj") or {}
    summary = {
        key: len(value)
        if isinstance(value, list)
        else sorted(value.keys())
        if isinstance(value, dict)
        else type(value).__name__
        for key, value in obj.items()
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: /apiv2/load 已导出到 {raw_path}")
    print(f"OK: 摘要已写入 {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
