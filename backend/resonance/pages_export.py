"""Refresh and export the existing daily resonance calculation for GitHub Pages."""

from __future__ import annotations

import argparse
import json
from contextlib import closing
from datetime import datetime, time, timedelta
from html import escape
from pathlib import Path
from string import Template
from typing import Any
from zoneinfo import ZoneInfo

from base.analysis.sentiment.core import enrich_turnover
from base.config import DEFAULT_ETF_SEED_DAYS, ETFS, SHARE_WINDOW
from base.scheduler.data_jobs import job_sync_calendar
from base.scheduler.etf_daily_jobs import job_backfill_etf_daily
from base.scheduler.sentiment_jobs import job_fetch_sentiment
from base.scheduler.shares_jobs import job_backfill_shares
from base.store.calendar_repo import get_last_trading_day, get_range
from base.store.daily_repo import get_by_code, get_latest_date, get_trading_dates
from base.store.database import get_connection, init_db
from base.store.etf_repo import load_into_config, seed_from_config
from base.store.sentiment_repo import get_margin_series, get_turnover_series
from resonance.analysis.core import compute_resonance, verdict_of

SHANGHAI = ZoneInfo("Asia/Shanghai")
SHARE_BACKFILL_DAYS = SHARE_WINDOW + 5
HISTORY_DAYS = 60
INCREMENTAL_LOOKBACK_DAYS = 10
CLOSE_TIME = time(15, 0)
CALENDAR_DAYS_PER_TRADING_DAY = 1.6
UPSTREAM = "https://github.com/OrangesHuang/Resonance"
RADAR = "https://trynocoding.github.io/etf-radar/"
FLOW = "https://trynocoding.github.io/national-team-etf-flow/"


def progress(current: int, total: int, message: str) -> None:
    print(f"[{current}/{total}] {message}", flush=True)


def refresh(now: datetime) -> dict[str, Any]:
    """Reuse the existing collectors without starting the live scheduler."""
    today = now.date().isoformat()
    _, calendar_end = get_range()
    if not calendar_end or calendar_end < today:
        job_sync_calendar(progress)

    settled_day = now.date() if now.time() >= CLOSE_TIME else now.date() - timedelta(days=1)
    target = get_last_trading_day(settled_day.isoformat())
    previous = get_latest_date()
    if previous:
        recent = (now.date() - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)).isoformat()
        start = min(previous, recent)
    else:
        start = (settled_day - timedelta(days=int(DEFAULT_ETF_SEED_DAYS * CALENDAR_DAYS_PER_TRADING_DAY))).isoformat()
    daily = job_backfill_etf_daily(progress, start_date=start, end_date=target)
    if not get_latest_date():
        raise RuntimeError("ETF 日线采集未生成任何记录")

    sentiment = job_fetch_sentiment(progress, end_date=target)
    shares_target = get_last_trading_day((now.date() - timedelta(days=1)).isoformat())
    share_dates = get_trading_dates(end=shares_target)[-SHARE_BACKFILL_DAYS:]
    shares = (
        job_backfill_shares(progress, start_date=share_dates[0], end_date=share_dates[-1], codes=list(ETFS))
        if share_dates
        else {}
    )
    return {"target_trade_date": target, "etf_daily": daily, "sentiment": sentiment, "shares": shares}


def snapshot(now: datetime, collection: dict[str, Any]) -> dict[str, Any]:
    turnover = get_turnover_series()
    margin = get_margin_series()
    enriched_turnover = enrich_turnover(turnover)
    etfs = []
    for code, info in ETFS.items():
        daily = list(reversed(get_by_code(code, end=collection["target_trade_date"])))
        analysis = compute_resonance(
            code, [row for row in daily if row.get("composite_prob") is not None], enriched_turnover, margin
        )
        history = analysis["history"][-HISTORY_DAYS:]
        daily_by_date = {row["date"]: row for row in daily}
        for item in history:
            item["verdict"] = verdict_of(item["red"], item["green"])
            daily_row = daily_by_date[item["date"]]
            item["close_price"] = daily_row["close_price"]
            item["shares_yi"] = daily_row["shares_yi"]
            item["shares_delta_yi"] = daily_row["shares_delta_yi"]
        analysis.update(
            history=history,
            name=info["name"],
            index=info["idx"],
            market=info["market"],
            quote_date=max((row["date"] for row in daily if row.get("close_price") is not None), default=None),
            shares_date=max((row["date"] for row in daily if row.get("shares_yi") is not None), default=None),
        )
        if not any(indicator["value"] is not None for indicator in analysis["indicators"]):
            analysis["verdict"] = None
        etfs.append(analysis)
    if not any(etf["verdict"] is not None for etf in etfs):
        raise RuntimeError("未生成有效的共振记录，请检查 ETF 日线、成交额与融资数据源")

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "upstream": UPSTREAM,
        "target_trade_date": collection["target_trade_date"],
        "market_data_dates": {
            "turnover": max((row["date"] for row in turnover), default=None),
            "margin": max((row["date"] for row in margin), default=None),
        },
        "related_sources": {
            "etf_radar": {"holdings_json": RADAR + "data/etfs.json", "metadata_json": RADAR + "data/meta.json"},
            "national_team_etf_flow": {"core_report_html": FLOW, "broad_report_html": FLOW + "broad.html"},
        },
        "etfs": etfs,
    }


def render_page(template: Path, data: dict[str, Any]) -> str:
    def cell(value: str | None) -> str:
        return escape(value or "—")

    rows = []
    for etf in data["etfs"]:
        lights = (
            "".join(
                f'<td><span class="{escape(item["state"], quote=True)}">{cell(item["display"])}</span></td>'
                for item in etf["indicators"]
            )
            or '<td colspan="5">暂无指标</td>'
        )
        rows.append(
            f'<tr><th scope="row">{cell(etf["code"])}<small>{cell(etf["name"])}</small></th>'
            f"<td>{cell(etf['date'])}</td><td>{cell(etf['quote_date'])}</td>"
            f"<td>{cell(etf['shares_date'])}</td><td>{cell(etf['verdict'])}</td>{lights}</tr>"
        )
    return Template(template.read_text(encoding="utf-8")).substitute(
        rows="\n".join(rows),
        generated_at=cell(data["generated_at"]),
        target_date=cell(data["target_trade_date"]),
        turnover_date=cell(data["market_data_dates"]["turnover"]),
        margin_date=cell(data["market_data_dates"]["margin"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()

    init_db()
    seed_from_config()
    load_into_config()
    collection = refresh(datetime.now(SHANGHAI))
    print(json.dumps(collection, ensure_ascii=False), flush=True)
    data = snapshot(datetime.now(SHANGHAI), collection)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "resonance.json").write_text(
        json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (args.output / "index.html").write_text(render_page(args.template, data), encoding="utf-8")
    with closing(get_connection()) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"Exported {len(data['etfs'])} ETFs", flush=True)


if __name__ == "__main__":
    main()
