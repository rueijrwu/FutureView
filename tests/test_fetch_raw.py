from __future__ import annotations

import os
from pathlib import Path

import pytest

from futureview_replay import fetch_raw as fetch_raw_module


def test_object_url_preserves_r2_key_slashes() -> None:
    url = fetch_raw_module._object_url(
        "abc123",
        "futureview-data",
        "raw/databento/GLBX.MDP3/MES/ohlcv-1m/file name.dbn.zst",
    )
    assert url == (
        "https://api.cloudflare.com/client/v4/accounts/abc123/r2/buckets/"
        "futureview-data/objects/raw/databento/GLBX.MDP3/MES/ohlcv-1m/file%20name.dbn.zst"
    )


def test_cloudflare_credentials_accepts_r2_account_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("R2_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    assert fetch_raw_module._cloudflare_credentials() == ("account", "token")


def test_cloudflare_credentials_reports_missing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="Direct R2 fetch requires Cloudflare credentials"):
        fetch_raw_module._cloudflare_credentials()
