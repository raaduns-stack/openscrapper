import subprocess

import pytest

from src.browser.openclaw import OpenClawBrowser


def test_openclaw_timeout_is_bounded(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    browser = OpenClawBrowser(cli="openclaw", timeout=2)

    with pytest.raises(RuntimeError, match="timed out after 2s"):
        browser.snapshot()

    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 2


def test_openclaw_timeout_must_be_positive():
    with pytest.raises(ValueError, match="timeout must be positive"):
        OpenClawBrowser(timeout=0)
