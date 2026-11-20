"""Unit tests with a fake transport: no network. The sample answers are copies of
real API answers (20 Nov 2026)."""
import io
import json
import urllib.error

import pytest

from zentriaflow import Client, RateLimited, ZentriaFlowError
from zentriaflow.cli import main

TSHIRT_CN = {
    "ok": True, "hts": "6109.10.00", "digits": "61091000", "origin": "CN",
    "description": "T-shirts, singlets, tank tops and similar garments, knitted or crocheted - Of cotton",
    "mfn": {"rate": 16.5, "text": "16.5%", "exact": True}, "us_mfn": None,
    "section_301": {"rate": 7.5, "heading": "9903.88.15", "label": "List 4A", "partial": False, "note": ""},
    "forced_labor": {"rate": 12.5, "status": "applies", "tier": "12.5% flat", "reason": "", "covered_origin": True},
    "section_232": {"rate": 0.0, "program": None, "note": "", "conditional": []},
    "section_338": {"rate": 0.0, "program": None, "heading": None, "partial": False, "note": ""},
    "import_ban": None, "upcoming": None, "total_rate": 36.5, "usmca": None, "cafta_dr": None,
    "notes": [], "source": "HTSUS 2026 Revision 23", "as_of": "2026-11-20", "as_of_is_today": True,
    "scheduled_changes": [],
}
CABINETS_VN = dict(TSHIRT_CN, hts="9403.40.90.60", origin="VN", total_rate=25.0,
                   scheduled_changes=[{"effective_date": "2027-01-01", "total_rate_before_pct": 25,
                                       "total_rate_after_pct": 50}])


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return FakeResponse(json.dumps(a).encode("utf-8"))


def http_error(code, body, retry=None):
    headers = {"Retry-After": str(retry)} if retry is not None else {}
    return urllib.error.HTTPError("https://zentriaflow.com/x", code, "err", headers,
                                  io.BytesIO(json.dumps(body).encode("utf-8")))


def test_tariff_check_reads_layers_and_total():
    op = FakeOpener([TSHIRT_CN])
    r = Client(opener=op).tariff_check("6109.10.00", "CN")
    assert r.total_rate == 36.5
    names = [(l["key"], l["rate"]) for l in r.layers]
    assert names == [("mfn", 16.5), ("section_301", 7.5), ("forced_labor", 12.5),
                     ("section_232", 0.0), ("section_338", 0.0)]
    assert r.layers[1]["label"] == "Section 301" and r.layers[1]["list"] == "List 4A"
    assert r.duty(10000) == 3650.0
    url = op.calls[0].full_url
    assert url.startswith("https://zentriaflow.com/api/public-tools/tariff-check?")
    assert "hts=6109.10.00" in url and "origin=CN" in url and "as_of" not in url
    assert op.calls[0].get_header("User-agent").startswith("zentria-flow-python/")


def test_as_of_is_sent_and_changes_are_exposed():
    op = FakeOpener([CABINETS_VN])
    r = Client(opener=op).tariff_check("9403.40.9060", "VN", as_of="2027-01-02")
    assert "as_of=2027-01-02" in op.calls[0].full_url
    assert r.scheduled_changes[0]["total_rate_after_pct"] == 50


@pytest.mark.parametrize("hts", ["61", "abc", "61091000000000"])
def test_bad_hts_is_refused_before_any_request(hts):
    op = FakeOpener([])
    with pytest.raises(ValueError):
        Client(opener=op).tariff_check(hts, "CN")
    assert op.calls == []


def test_compare_sorts_lowest_total_first():
    vn = dict(TSHIRT_CN, origin="VN", total_rate=29.0)
    op = FakeOpener([TSHIRT_CN, vn])
    rows = Client(opener=op).compare_origins("6109.10.00", ["CN", "VN"], gap=0)
    assert [r["origin"] for r in rows] == ["VN", "CN"]


def test_rate_limit_raises_with_retry_after():
    op = FakeOpener([http_error(429, {"detail": "Free lookup limit reached."}, retry=30)])
    with pytest.raises(RateLimited) as e:
        Client(opener=op).tariff_check("6109.10.00", "CN")
    assert e.value.retry_after == 30 and e.value.status == 429


def test_wait_on_limit_retries_once(monkeypatch):
    slept = []
    monkeypatch.setattr("zentriaflow.client.time.sleep", lambda s: slept.append(s))
    op = FakeOpener([http_error(429, {"detail": "limit"}, retry=2), TSHIRT_CN])
    r = Client(opener=op, wait_on_limit=True).tariff_check("6109.10.00", "CN")
    assert r.total_rate == 36.5 and slept == [2]


def test_other_http_errors_carry_the_api_message():
    op = FakeOpener([http_error(422, {"detail": "origin is not a country we know."})])
    with pytest.raises(ZentriaFlowError, match="origin is not a country"):
        Client(opener=op).tariff_check("6109.10.00", "Atlantis")


def test_price_rows_adds_rate_duty_and_next_change():
    op = FakeOpener([TSHIRT_CN, CABINETS_VN])
    out = Client(opener=op).price_rows([
        {"hts": "6109.10.00", "origin": "CN", "value": "12000"},
        {"hts": "9403.40.9060", "origin": "VN", "value": 40000},
    ], gap=0)
    assert out[0]["total_rate"] == 36.5 and out[0]["duty"] == 4380.0 and out[0]["next_change"] is None
    assert out[1]["duty"] == 10000.0 and out[1]["next_change"]["effective_date"] == "2027-01-01"


def test_price_rows_stops_at_the_limit():
    op = FakeOpener([TSHIRT_CN, http_error(429, {"detail": "limit"})])
    out = Client(opener=op).price_rows([{"hts": "6109.10.00", "origin": "CN"}] * 3, gap=0)
    assert len(out) == 2 and "error" in out[1]


def test_calendar_filters_by_origin():
    cal = {"events": [
        {"date": "2026-12-04", "program": "Section 232 solar", "scope": {"origins": []}},
        {"date": "2027-01-01", "program": "Nicaragua Section 301", "scope": {"origins": ["NI"]}},
    ]}
    op = FakeOpener([cal])
    ev = Client(opener=op).tariff_calendar(origin="VN")
    assert [e["program"] for e in ev] == ["Section 232 solar"]


def test_cli_check_prints_layers(monkeypatch, capsys):
    op = FakeOpener([TSHIRT_CN])
    monkeypatch.setattr("zentriaflow.cli.Client", lambda **kw: Client(opener=op, **kw))
    assert main(["check", "6109.10.00", "CN"]) == 0
    out = capsys.readouterr().out
    assert "Total US duty" in out and "36.5%" in out and "(List 4A)" in out
