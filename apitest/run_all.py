#!/usr/bin/env python3
"""Run one isolated database per URL/method case and write an HTML report."""
import html
import importlib.util
import os
from pathlib import Path
import sys
import traceback
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from apitest.support import isolated_case  # noqa: E402


def run():
    cases = sorted((HERE / "cases").rglob("*.py"))
    results = []
    for path in cases:
        name = str(path.relative_to(HERE))
        try:
            spec = importlib.util.spec_from_file_location(
                "apitest_" + str(len(results)), path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with isolated_case() as context:
                module.run(context)
            results.append((name, "PASS", ""))
            print("PASS", name)
        except Exception:
            details = traceback.format_exc()
            results.append((name, "FAIL", details))
            print("FAIL", name)
            print(details)
    if os.environ.get("APITEST_FORCE_FAIL") == "1":
        results.append(("self-test", "FAIL", "Intentional report and exit-code check"))
    report_dir = HERE / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "latest.html"
    timestamp = datetime.now(timezone.utc).isoformat()
    rows = "".join(
        "<tr><td>" + html.escape(name) + "</td><td>" + status
        + "</td><td><pre>" + html.escape(details) + "</pre></td></tr>"
        for name, status, details in results
    )
    report_path.write_text(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<title>CampusClaw API Test Report</title>"
        "<style>body{font:15px sans-serif;margin:2rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #bbb;padding:.6rem;vertical-align:top}"
        "pre{white-space:pre-wrap}</style>"
        "<h1>接口测试报告</h1><p>" + html.escape(timestamp)
        + "</p><p>通过 " + str(sum(status == "PASS" for _, status, _ in results))
        + " / " + str(len(results)) + "</p>"
        "<table><tr><th>接口脚本</th><th>结果</th><th>失败详情</th></tr>"
        + rows + "</table></html>",
        encoding="utf-8",
    )
    print("Report:", report_path)
    return 0 if results and all(status == "PASS" for _, status, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
