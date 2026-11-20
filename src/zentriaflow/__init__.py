"""Zentria Flow: free US import duty lookups by HTS code and country of origin.

    from zentriaflow import Client
    c = Client()
    c.tariff_check("6109.10.00", "CN").total_rate

Planning estimates, not customs rulings. https://zentriaflow.com/developers
"""
__version__ = "0.1.0"

from .client import (  # noqa: E402
    DISCLAIMER,
    Client,
    RateLimited,
    TariffResult,
    ZentriaFlowError,
)

_default = None


def _client() -> "Client":
    global _default
    if _default is None:
        _default = Client()
    return _default


def tariff_check(hts, origin, **kw):
    """Every US tariff layer for one HTS code from one origin (default client)."""
    return _client().tariff_check(hts, origin, **kw)


def compare_origins(hts, origins, **kw):
    """The same HTS code from 2 to 6 origins, lowest total first (default client)."""
    return _client().compare_origins(hts, origins, **kw)


def hts_search(query):
    """Candidate HTSUS lines for product words (default client)."""
    return _client().hts_search(query)


def tariff_calendar(**kw):
    """Dated US tariff changes (default client)."""
    return _client().tariff_calendar(**kw)


__all__ = ["Client", "TariffResult", "ZentriaFlowError", "RateLimited", "DISCLAIMER",
           "tariff_check", "compare_origins", "hts_search", "tariff_calendar", "__version__"]
