"""Export public market data from a copy of the server's Resonance database."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from base.analysis.sentiment.core import enrich_turnover
from base.config import DB_PATH, ETFS
from base.store.calendar_repo import get_last_trading_day
from base.store.daily_repo import get_by_code
from base.store.etf_repo import load_into_config
from base.store.sentiment_repo import get_margin_series, get_turnover_series
from resonance.analysis.core import compute_resonance, verdict_of

SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_TIME = time(15, 0)
UPSTREAM = "https://github.com/OrangesHuang/Resonance"
RADAR = "https://trynocoding.github.io/etf-radar/"
FLOW = "https://trynocoding.github.io/national-team-etf-flow/"
DAILY_FIELDS = (
    "date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "change_pct",
    "volume",
    "shares_yi",
    "shares_delta_yi",
    "shares_delta_pct",
    "price_position",
    "share_prob",
    "composite_prob",
)
TURNOVER_FIELDS = ("date", "sh_amount_yi", "sz_amount_yi", "total_amount_yi")
MARGIN_FIELDS = ("date", "fin_balance_yi", "loan_balance_yi", "fin_buy_yi")
HISTORY_PRICE_FIELDS = ("close_price", "shares_yi", "shares_delta_yi")


def etf_history(code: str, target: str, turnover: list[dict], margin: list[dict]) -> dict[str, Any]:
    """Keep both the full daily series and the subset with computed resonance."""
    info = ETFS[code]
    daily = list(reversed(get_by_code(code, end=target)))
    analysis = compute_resonance(
        code, [row for row in daily if row.get("composite_prob") is not None], turnover, margin
    )
    daily_by_date = {row["date"]: row for row in daily}
    for item in analysis["history"]:
        item["verdict"] = verdict_of(item["red"], item["green"])
        item.update({key: daily_by_date[item["date"]].get(key) for key in HISTORY_PRICE_FIELDS})
    analysis.update(
        name=info["name"],
        index=info["idx"],
        market=info["market"],
        quote_date=max((row["date"] for row in daily if row.get("close_price") is not None), default=None),
        shares_date=max((row["date"] for row in daily if row.get("shares_yi") is not None), default=None),
        daily=[{key: row.get(key) for key in DAILY_FIELDS} for row in daily],
    )
    if not any(indicator["value"] is not None for indicator in analysis["indicators"]):
        analysis["verdict"] = None
    return analysis


def snapshot(now: datetime) -> dict[str, Any]:
    settled_day = now.date() if now.time() >= CLOSE_TIME else now.date() - timedelta(days=1)
    target = get_last_trading_day(settled_day.isoformat())
    turnover = [row for row in get_turnover_series() if row["date"] <= target]
    margin = [row for row in get_margin_series() if row["date"] <= target]
    enriched_turnover = enrich_turnover(turnover)
    etfs = [etf_history(code, target, enriched_turnover, margin) for code in ETFS]
    if not any(etf["verdict"] is not None for etf in etfs):
        raise RuntimeError("数据库中没有可发布的共振记录")
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "upstream": UPSTREAM,
        "data_source": "resonance_server",
        "target_trade_date": target,
        "market_data_dates": {
            "turnover": turnover[-1]["date"] if turnover else None,
            "margin": margin[-1]["date"] if margin else None,
        },
        "market_history": {
            "turnover": [{key: row[key] for key in TURNOVER_FIELDS} for row in turnover],
            "margin": [{key: row[key] for key in MARGIN_FIELDS} for row in margin],
        },
        "related_sources": {
            "etf_radar": {"holdings_json": RADAR + "data/etfs.json", "metadata_json": RADAR + "data/meta.json"},
            "national_team_etf_flow": {"core_report_html": FLOW, "broad_report_html": FLOW + "broad.html"},
        },
        "etfs": etfs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not DB_PATH.is_file() or not load_into_config():
        raise RuntimeError("未找到包含 ETF 清单的数据库副本")
    data = snapshot(datetime.now(SHANGHAI))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"Exported {len(data['etfs'])} ETFs for {data['target_trade_date']}", flush=True)


if __name__ == "__main__":
    main()
