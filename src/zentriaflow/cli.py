"""zentria-flow: US import duty from the command line.

  zentria-flow check 6109.10.00 CN
  zentria-flow check 9403.40.9060 VN --as-of 2027-01-02
  zentria-flow compare 9405.31.00 CN VN KH MX
  zentria-flow search "cotton t-shirt"
  zentria-flow calendar --origin VN
  zentria-flow price products.csv          (columns: hts, origin, value)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__
from .client import DISCLAIMER, Client, ZentriaFlowError


def _pct(x):
    return "n/a" if x is None else f"{x:g}%"


def _print_check(r, as_json):
    if as_json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return
    print(f"HTS {r.get('hts')} from {r.get('origin')}  (entry date {r.get('as_of')})")
    if r.get("description"):
        print(f"  {r['description'][:150]}")
    for layer in r.layers:
        note = ""
        if layer["key"] == "forced_labor" and layer.get("status"):
            note = f"  ({layer['status']})"
        elif layer["key"] == "section_301" and (r.get("section_301") or {}).get("label"):
            note = f"  ({r['section_301']['label']})"
        print(f"  {layer['label']:<34} {_pct(layer.get('rate')):>7}{note}")
    print(f"  {'Total US duty':<34} {_pct(r.total_rate):>7}")
    for ch in r.scheduled_changes:
        print(f"  Scheduled: {ch.get('effective_date')}: {_pct(ch.get('total_rate_before_pct'))} -> "
              f"{_pct(ch.get('total_rate_after_pct'))}")
    if r.get("upcoming"):
        print(f"  Note: {r['upcoming']}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="zentria-flow", description="Free US import duty lookups (zentriaflow.com).")
    p.add_argument("--version", action="version", version=f"zentria-flow {__version__}")
    p.add_argument("--json", action="store_true", help="print the raw JSON answer")
    p.add_argument("--wait", action="store_true", help="wait and retry once when the free limit is hit")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="every tariff layer for one HTS code and origin")
    c.add_argument("hts"); c.add_argument("origin"); c.add_argument("--as-of")

    m = sub.add_parser("compare", help="one HTS code from 2 to 6 origins")
    m.add_argument("hts"); m.add_argument("origins", nargs="+")

    s = sub.add_parser("search", help="find HTS codes by product words")
    s.add_argument("query", nargs="+")

    k = sub.add_parser("calendar", help="dated US tariff changes")
    k.add_argument("--origin"); k.add_argument("--months", type=int, default=12)

    pr = sub.add_parser("price", help="price a CSV product list (hts, origin, value)")
    pr.add_argument("csv_file")

    a = p.parse_args(argv)
    client = Client(wait_on_limit=a.wait)
    try:
        if a.cmd == "check":
            _print_check(client.tariff_check(a.hts, a.origin, as_of=a.as_of), a.json)
        elif a.cmd == "compare":
            rows = client.compare_origins(a.hts, a.origins)
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            else:
                print(f"HTS {a.hts}, total US duty, lowest first:")
                for r in rows:
                    print(f"  {r.get('origin'):<4} {_pct(r.total_rate):>7}")
        elif a.cmd == "search":
            res = client.hts_search(" ".join(a.query))
            if a.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            for r in ([] if a.json else res):
                desc = str(r.get("description") or "")
                short = desc.split(" — ", 1)[1] if " — " in desc else desc   # the line's own words
                print(f"  {r.get('hts'):<12} {short[:110]}")
        elif a.cmd == "calendar":
            ev = client.tariff_calendar(months=a.months, origin=a.origin)
            if a.json:
                print(json.dumps(ev, indent=2, ensure_ascii=False))
            for e in ([] if a.json else ev):
                print(f"  {e.get('date')}  {e.get('program')}: {str(e.get('what_changes'))[:120]}")
        elif a.cmd == "price":
            with open(a.csv_file, newline="", encoding="utf-8-sig") as f:
                rows = [{k.strip().lower(): v for k, v in row.items()} for row in csv.DictReader(f)]
            out = client.price_rows(rows)
            w = csv.DictWriter(sys.stdout, fieldnames=list(out[0].keys()) if out else ["hts"], extrasaction="ignore")
            w.writeheader()
            for row in out:
                row = dict(row)
                if isinstance(row.get("next_change"), dict):
                    ch = row["next_change"]
                    row["next_change"] = f"{ch.get('effective_date')}: {ch.get('total_rate_before_pct')}% -> {ch.get('total_rate_after_pct')}%"
                w.writerow(row)
    except ZentriaFlowError as e:
        print(f"zentria-flow: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"zentria-flow: {e}", file=sys.stderr)
        return 2
    if not a.json:
        print(f"\n{DISCLAIMER}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
