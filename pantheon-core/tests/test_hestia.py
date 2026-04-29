"""Tests for gods/hestia.py — HestiaChecker health checks."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from gods.hestia import HealthStatus, HestiaChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    return resp


def _make_checker() -> HestiaChecker:
    return HestiaChecker()


# ---------------------------------------------------------------------------
# Individual check methods
# ---------------------------------------------------------------------------


class TestCheckOllama:
    def test_returns_ok_on_200(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(200)
            result = checker.check_ollama()
        assert result.service == "ollama"
        assert result.ok is True
        assert result.latency_ms is not None
        assert result.error is None

    def test_returns_failure_on_500(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(500)
            result = checker.check_ollama()
        assert result.ok is False
        assert "500" in result.error

    def test_returns_failure_on_connection_error(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.side_effect = httpx.ConnectError("refused")
            result = checker.check_ollama()
        assert result.ok is False
        assert result.error is not None

    def test_custom_host_and_port(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(200)
            result = checker.check_ollama(host="myhost", port=9999)
        assert result.ok is True
        call_url = ctx.get.call_args[0][0]
        assert "myhost:9999" in call_url


class TestCheckChromadb:
    def test_returns_ok_on_200(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(200)
            result = checker.check_chromadb()
        assert result.service == "chromadb"
        assert result.ok is True

    def test_returns_failure_on_exception(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.side_effect = TimeoutError("timed out")
            result = checker.check_chromadb()
        assert result.ok is False
        assert "timed out" in result.error


class TestCheckPantheonApi:
    def test_returns_ok_on_200(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(200)
            result = checker.check_pantheon_api()
        assert result.service == "pantheon-api"
        assert result.ok is True

    def test_404_is_still_ok(self):
        """4xx responses mean the server is alive — we accept < 500."""
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(404)
            result = checker.check_pantheon_api()
        assert result.ok is True


# ---------------------------------------------------------------------------
# check_all / all_healthy
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_returns_three_statuses(self):
        checker = _make_checker()
        with patch("gods.hestia.httpx.Client") as mock_client_cls:
            ctx = mock_client_cls.return_value.__enter__.return_value
            ctx.get.return_value = _mock_response(200)
            results = checker.check_all()
        assert len(results) == 3
        services = {r.service for r in results}
        assert services == {"ollama", "chromadb", "pantheon-api"}

    def test_all_healthy_true_when_all_ok(self):
        checker = _make_checker()
        with patch.object(
            checker,
            "check_all",
            return_value=[
                HealthStatus(service="ollama", ok=True, latency_ms=5.0),
                HealthStatus(service="chromadb", ok=True, latency_ms=3.0),
                HealthStatus(service="pantheon-api", ok=True, latency_ms=7.0),
            ],
        ):
            assert checker.all_healthy() is True

    def test_all_healthy_false_when_one_down(self):
        checker = _make_checker()
        with patch.object(
            checker,
            "check_all",
            return_value=[
                HealthStatus(service="ollama", ok=True, latency_ms=5.0),
                HealthStatus(service="chromadb", ok=False, error="refused"),
                HealthStatus(service="pantheon-api", ok=True, latency_ms=7.0),
            ],
        ):
            assert checker.all_healthy() is False

    def test_all_healthy_false_when_all_down(self):
        checker = _make_checker()
        with patch.object(
            checker,
            "check_all",
            return_value=[
                HealthStatus(service="ollama", ok=False, error="refused"),
                HealthStatus(service="chromadb", ok=False, error="refused"),
                HealthStatus(service="pantheon-api", ok=False, error="refused"),
            ],
        ):
            assert checker.all_healthy() is False
