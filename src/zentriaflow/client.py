"""A small client for the free Zentria Flow US tariff API (no key, no account).

Every number comes from the Zentria Flow engine at zentriaflow.com: nothing is
estimated or filled in here. Results are planning estimates, not customs rulings.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import __version__

BASE_URL = "https://zentriaflow.com"
USER_AGENT = f"zentria-flow-python/{__version__} (+https://zentriaflow.com/developers)"
DISCLAIMER = ("Planning estimate, not a customs ruling. Anti-dumping and countervailing duties are "
              "company-specific and are not in any total. Confirm classification and rates with a "
              "licensed customs broker before entry.")

_LAYERS = (
    ("mfn", "MFN duty"),
    ("section_301", "Section 301"),
    ("forced_labor", "Forced-labor Section 301 tariff"),
    ("section_232", "Section 232"),
    ("section_338", "Section 338 (Canada)"),
)


class ZentriaFlowError(Exception):
    """The API refused the request or could not be reached."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class RateLimited(ZentriaFlowError):
    """The free allowance for this IP address is used up for now (HTTP 429)."""

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message, status=429)
        self.retry_after = retry_after


class TariffResult(dict):
    """The API answer for one HTS code and origin, as a dict, with shortcuts."""

    @property
    def total_rate(self) -> Optional[float]:
        """Total US duty in percent of the customs value (None if the API sent none)."""
        return self.get("total_rate")

    @property
    def layers(self) -> List[Dict[str, Any]]:
        """Each duty layer as {"key", "label", "rate", ...} in a fixed order."""
        out = []
        for key, label in _LAYERS:
            part = self.get(key)
            if isinstance(part, dict):
                # the API's own "label" (e.g. "List 4A" for Section 301) is kept as "list"
                out.append({**part, "key": key, "label": label, "list": part.get("label")})
        return out

    @property
    def scheduled_changes(self) -> List[Dict[str, Any]]:
        """Dated changes already on file for this line (rate before and after)."""
        return list(self.get("scheduled_changes") or [])

    def duty(self, customs_value: float) -> Optional[float]:
        """Duty in dollars for a customs value, from the total rate (ad valorem part only)."""
        if self.total_rate is None:
            return None
        return round(customs_value * self.total_rate / 100.0, 2)


def _clean_hts(hts: str) -> str:
    text = str(hts).strip()
    digits = re.sub(r"[.\s-]", "", text)
    if not digits.isdigit() or not 4 <= len(digits) <= 10 or len(text) > 20:
        raise ValueError(f"hts must have 4 to 10 digits, for example 6109.10.00 (got {hts!r}).")
    return text


def _clean_origin(origin: str) -> str:
    text = str(origin).strip()
    if not 2 <= len(text) <= 60:
        raise ValueError(f"origin must be a country name or ISO-2 code, for example CN (got {origin!r}).")
    return text


class Client:
    """Free Zentria Flow US tariff lookups.

    >>> from zentriaflow import Client
    >>> r = Client().tariff_check("6109.10.00", "CN")
    >>> r.total_rate        # e.g. 36.5
    """

    def __init__(self, base_url: str = BASE_URL, timeout: float = 30.0, wait_on_limit: bool = False,
                 max_wait: float = 120.0, user_agent: str = USER_AGENT, opener=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.wait_on_limit = wait_on_limit
        self.max_wait = max_wait
        self.user_agent = user_agent
        self._open = opener or urllib.request.urlopen

    # ── transport ────────────────────────────────────────────────────────────
    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": self.user_agent})
        for attempt in range(2):
            try:
                with self._open(req, timeout=self.timeout) as res:
                    return json.loads(res.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = _read_error(e)
                if e.code == 429:
                    retry = _int(e.headers.get("Retry-After") if e.headers else None)
                    if self.wait_on_limit and attempt == 0 and retry is not None and retry <= self.max_wait:
                        time.sleep(retry)
                        continue
                    raise RateLimited(body or "Free lookup limit reached for now.", retry) from None
                raise ZentriaFlowError(body or f"HTTP {e.code}", e.code) from None
            except urllib.error.URLError as e:
                raise ZentriaFlowError(f"Could not reach {self.base_url}: {e.reason}") from None
        raise RateLimited("Free lookup limit reached for now.")

    # ── lookups ──────────────────────────────────────────────────────────────
    def tariff_check(self, hts: str, origin: str, as_of: Optional[str] = None,
                     quantity: Optional[float] = None, value: Optional[float] = None,
                     quantity_unit: Optional[str] = None) -> TariffResult:
        """Every US tariff layer for one HTS code from one origin.

        as_of: entry date YYYY-MM-DD, today to 12 months ahead (default today).
        quantity/value: optional, to price a specific or compound duty exactly.
        """
        data = self._get("/api/public-tools/tariff-check", {
            "hts": _clean_hts(hts), "origin": _clean_origin(origin), "as_of": as_of,
            "quantity": quantity, "value": value, "quantity_unit": quantity_unit})
        if isinstance(data, dict) and data.get("ok") is False:
            raise ZentriaFlowError(str(data.get("error") or data.get("detail") or "Lookup refused."))
        return TariffResult(data)

    def compare_origins(self, hts: str, origins: Sequence[str], as_of: Optional[str] = None,
                        gap: float = 1.0) -> List[TariffResult]:
        """The same HTS code from several origins, lowest total first (duty only)."""
        if not 2 <= len(origins) <= 6:
            raise ValueError("Give 2 to 6 origins.")
        results = []
        for i, origin in enumerate(origins):
            if i and gap:
                time.sleep(gap)
            results.append(self.tariff_check(hts, origin, as_of=as_of))
        return sorted(results, key=lambda r: (r.total_rate is None, r.total_rate or 0))

    def hts_search(self, query: str) -> List[Dict[str, str]]:
        """Candidate 8-digit HTSUS lines for product words or the start of a code."""
        q = str(query).strip()
        if len(q) < 2:
            raise ValueError("query needs at least 2 characters.")
        data = self._get("/api/public-tools/hts-search", {"q": q[:80]})
        return list((data or {}).get("results") or [])

    def tariff_calendar(self, months: int = 12, origin: Optional[str] = None) -> List[Dict[str, Any]]:
        """Dated US tariff changes (from 30 days ago to `months` ahead).

        origin: optional ISO-2 code; keeps changes that name it or cover every origin.
        """
        if not 1 <= int(months) <= 12:
            raise ValueError("months must be 1 to 12.")
        data = self._get("/api/public-tools/tariff-calendar", {"months": int(months)})
        events = list((data or {}).get("events") or [])
        if origin:
            iso = origin.strip().upper()
            events = [e for e in events if not (e.get("scope") or {}).get("origins")
                      or iso in (e.get("scope") or {}).get("origins")]
        return events

    def price_rows(self, rows: Iterable[Dict[str, Any]], gap: float = 0.5) -> List[Dict[str, Any]]:
        """Price a product list: each row needs "hts" and "origin", "value" (USD) is optional.

        Returns the rows with total_rate, duty and next_change added (or "error").
        The free API allows about 60 checks an hour per IP; use wait_on_limit=True
        on the Client to pause and retry when the limit is hit.
        """
        out = []
        for i, row in enumerate(rows):
            if i and gap:
                time.sleep(gap)
            item = dict(row)
            try:
                r = self.tariff_check(row["hts"], row["origin"], as_of=row.get("as_of"))
                item["total_rate"] = r.total_rate
                if row.get("value") not in (None, ""):
                    item["duty"] = r.duty(float(row["value"]))
                nxt = r.scheduled_changes[:1]
                item["next_change"] = nxt[0] if nxt else None
            except (ZentriaFlowError, ValueError, KeyError) as e:
                item["error"] = str(e)
                if isinstance(e, RateLimited):
                    out.append(item)
                    break
            out.append(item)
        return out


def _read_error(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8"))
    except Exception:
        return ""
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("error") or "")
    return ""


def _int(v) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None
