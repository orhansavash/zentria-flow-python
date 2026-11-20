# zentria-flow

Free US import duty lookups from Python and the command line: every tariff layer for an HTS code and a country of origin (MFN duty, Section 301, the forced-labor Section 301 tariff, Section 232, Section 338 on Canada), the total, and the tariff changes already dated for that line.

No API key, no account, no dependencies. Answers come from the [Zentria Flow](https://zentriaflow.com) tariff engine (HTSUS 2026 Revision 23 plus the chapter 99 programs).

```bash
pip install zentria-flow
```

## Command line

```console
$ zentria-flow check 9405.31.00 CN
HTS 9405.31.00 from CN  (entry date 2026-11-20)
  MFN duty                                8%
  Section 301                            25%  (List 3)
  Forced-labor Section 301 tariff      12.5%  (applies)
  Section 232                             0%
  Section 338 (Canada)                    0%
  Total US duty                        45.5%

$ zentria-flow check 9403.40.9060 VN --as-of 2027-01-02     # kitchen cabinets after 1 Jan
  Section 232                            50%
  Total US duty                          50%

$ zentria-flow compare 9503.00.00 CN VN                     # toys
  CN     12.5%
  VN     12.5%

$ zentria-flow search christmas lights
$ zentria-flow calendar --origin VN                          # dated changes that hit Vietnam
$ zentria-flow price products.csv > priced.csv               # columns: hts, origin, value
```

Rates above were checked on 20 Nov 2026. They change: run the command for today's answer.

## Python

```python
from zentriaflow import Client

c = Client()
r = c.tariff_check("6109.10.00", "CN")      # cotton T-shirt from China
r.total_rate                                 # 36.5
[(l["label"], l["rate"]) for l in r.layers]  # each tariff layer
r.duty(12_000)                               # 4380.0 (ad valorem part)
r.scheduled_changes                          # dated changes already on file

c.compare_origins("9405.31.00", ["CN", "VN", "KH", "MX"])   # lowest total first
c.hts_search("cotton t-shirt")
c.tariff_calendar(origin="VN")

rows = [{"hts": "9403.40.9060", "origin": "VN", "value": 40000}]
c.price_rows(rows)    # adds total_rate, duty and next_change to each row
```

`as_of="YYYY-MM-DD"` prices an entry date up to 12 months ahead. US duty is set on the day goods are entered, so a December order entered in January pays January's rate.

## Limits

The free API allows about 60 tariff checks an hour per IP address (searches and calendar reads have their own, larger allowance). `Client(wait_on_limit=True)` waits and retries once when the limit is hit. For higher volume, a key-based API with plans is at [zentriaflow.com/developers](https://zentriaflow.com/developers).

## Other ways to use the same engine

- A web page for a whole product list: [zentriaflow.com/bulk-tariff-check](https://zentriaflow.com/bulk-tariff-check)
- Google Sheets formulas (`=ZF_DUTY("6109.10.00","China")`): [zentriaflow.com/google-sheets](https://zentriaflow.com/google-sheets)
- An MCP server for Claude and other AI assistants: [github.com/orhansavash/zentria-flow-mcp](https://github.com/orhansavash/zentria-flow-mcp)

## Disclaimer

Planning estimates, not customs rulings. Anti-dumping and countervailing duties are company-specific and are not in any total. Confirm classification and rates with a licensed customs broker before entry.

MIT licensed. Zentria Flow, Inc.
