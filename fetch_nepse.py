#!/usr/bin/env python3
"""Fetch NEPSE market data with the nepse-data-api library and write data/nepse_live.json.

Run by the GitHub Action in .github/workflows/nepse-data.yml. If the library returns no
stock data, this script exits with an error and leaves the previous JSON file untouched,
so KAWACH keeps showing the last good data (and falls back to YONEPSE if it gets too old).
"""
import datetime as dt
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "nepse_live.json")


def first(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("content", "data", "items", "result"):
            if isinstance(x.get(k), list):
                return x[k]
    return []


def stamp(v, fallback):
    s = str(v) if v else ""
    return s[:19] if len(s) >= 10 and s[:4].isdigit() and s[4] == "-" else fallback


def round2(v):
    return None if v is None else round(v, 2)


def norm_stock(s, now_iso):
    symbol = first(s, ["symbol"])
    ltp = num(first(s, ["lastTradedPrice", "ltp", "closePrice"]))
    if not symbol or ltp is None:
        return None
    prev = num(first(s, ["previousClose", "previousDayClosePrice", "prevClose"]))
    if prev is not None and prev > 0:
        change = ltp - prev
        pct = change / prev * 100
    else:
        change = num(first(s, ["pointChange", "change"])) or 0.0
        pct = num(first(s, ["percentageChange", "percentChange"])) or 0.0
    return {
        "symbol": str(symbol),
        "name": str(first(s, ["securityName", "companyName", "name"], "")).strip(),
        "ltp": ltp,
        "previous_close": prev,
        "change": round2(change),
        "percent_change": round2(pct),
        "open": num(first(s, ["openPrice", "open"])),
        "high": num(first(s, ["highPrice", "high"])),
        "low": num(first(s, ["lowPrice", "low"])),
        "volume": num(first(s, ["totalTradeQuantity", "totalTradedQuantity", "volume"])),
        "turnover": num(first(s, ["totalTradeValue", "totalTradedValue", "turnover"])),
        "trades": num(first(s, ["totalTrades", "totalTransactions", "trades"])),
        "last_updated": stamp(first(s, ["lastUpdatedDateTime", "lastUpdated", "businessDate"]), now_iso),
    }


def norm_index(x, default_name=None):
    name = first(x, ["index", "indexName", "name"], default_name)
    close = num(first(x, ["close", "currentValue", "closingIndex"]))
    if not name or close is None:
        return None
    return {
        "index": str(name),
        "close": close,
        "previousClose": num(first(x, ["previousClose"])),
        "change": num(first(x, ["change"])),
        "perChange": num(first(x, ["perChange", "percentageChange"])),
        "high": num(first(x, ["high"])),
        "low": num(first(x, ["low"])),
        "generatedTime": str(first(x, ["generatedTime", "businessDate"], "")),
    }


def build(stocks_raw, idx_raw, sub_raw, status, errors, now_iso):
    stocks = [r for r in (norm_stock(s, now_iso) for s in stocks_raw if isinstance(s, dict)) if r]
    indices = []
    for i, x in enumerate(idx_raw):
        r = norm_index(x, "NEPSE Index" if i == 0 else None)
        if r:
            indices.append(r)
    for x in sub_raw:
        r = norm_index(x)
        if r:
            indices.append(r)
    return {
        "generated_at": now_iso + "Z",
        "source": "nepse-data-api (reads the Nepal Stock Exchange public data)",
        "market_status": status,
        "counts": {"stocks": len(stocks), "indices": len(indices)},
        "errors": errors,
        "stocks": stocks,
        "indices": indices,
        # first raw records, kept so field-name differences are easy to spot and fix
        "raw_sample": {
            "stock": stocks_raw[0] if stocks_raw else None,
            "index": idx_raw[0] if idx_raw else None,
            "sub_index": sub_raw[0] if sub_raw else None,
        },
    }


def main():
    from nepse_data_api import Nepse  # imported here so the helpers above can be tested without the library

    nepse = Nepse()
    errors = []

    def safe(name, fn):
        try:
            return fn()
        except Exception as e:  # keep going: one failed call should not lose the others
            errors.append(f"{name}: {e!r}")
            return None

    stocks_raw = as_list(safe("get_stocks", nepse.get_stocks))
    idx_raw = as_list(safe("get_nepse_index", nepse.get_nepse_index))
    sub_raw = as_list(safe("get_sub_indices", nepse.get_sub_indices))
    status = safe("get_market_status", nepse.get_market_status)

    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat()
    data = build(stocks_raw, idx_raw, sub_raw, status, errors, now_iso)

    if not data["stocks"]:
        print("No usable stock data returned. Errors:", errors, file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, OUT)
    print(f"Wrote {data['counts']['stocks']} stocks and {data['counts']['indices']} indices")


if __name__ == "__main__":
    main()
