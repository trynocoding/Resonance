"""Turn a server-exported JSON snapshot into the public Pages artifact."""

from __future__ import annotations

import argparse
import json
import shutil
from html import escape
from pathlib import Path
from string import Template
from typing import Any

HERE = Path(__file__).resolve().parent


def cell(value: str | None) -> str:
    return escape(value or "—")


def table_rows(etfs: list[dict[str, Any]]) -> str:
    rows = []
    for etf in etfs:
        lights = (
            "".join(
                f'<td><span class="{escape(item["state"])}">{cell(item["display"])}</span></td>'
                for item in etf["indicators"]
            )
            or '<td colspan="5">暂无指标</td>'
        )
        rows.append(
            f'<tr><th scope="row">{cell(etf["code"])}<small>{cell(etf["name"])}</small></th>'
            f"<td>{cell(etf['date'])}</td><td>{cell(etf['quote_date'])}</td>"
            f"<td>{cell(etf['shares_date'])}</td><td>{cell(etf['verdict'])}</td>{lights}</tr>"
        )
    return "\n".join(rows)


def build(source: Path, output: Path) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("data_source") != "resonance_server" or not data["etfs"]:
        raise ValueError("Expected a non-empty Resonance server export")
    if not any(etf["daily"] and etf["history"] for etf in data["etfs"]):
        raise ValueError("The export does not contain historical market data")

    template = Template((HERE / "index.template.html").read_text(encoding="utf-8"))
    html = template.substitute(
        rows=table_rows(data["etfs"]),
        generated_at=cell(data["generated_at"]),
        target_date=cell(data["target_trade_date"]),
        turnover_date=cell(data["market_data_dates"]["turnover"]),
        margin_date=cell(data["market_data_dates"]["margin"]),
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(html, encoding="utf-8")
    shutil.copyfile(source, output / "resonance.json")
    shutil.copyfile(HERE / "history.js", output / "history.js")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.output)
