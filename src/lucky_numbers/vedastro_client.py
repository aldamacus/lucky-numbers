"""Thin VedAstro client.

We hit the public MCP HTTP transport via JSON-RPC 2.0 `tools/call`.
The `refresh` CLI command uses this to update `data/snapshot.yaml`.

API key resolution order:
  1. explicit `api_key` argument
  2. environment variable VEDASTRO_API_KEY
  3. .env file in project root (auto-loaded if python-dotenv is installed)

For users who only run the offline engine, this module is optional.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_URL = "https://mcp.vedastro.org/api/mcp/public"


def _load_dotenv_if_present() -> None:
    """Minimal .env loader (no extra dependency required)."""
    root = Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class VedAstroClient:
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        _load_dotenv_if_present()
        self.url = url or os.getenv("VEDASTRO_URL", DEFAULT_URL)
        self.api_key = api_key or os.getenv("VEDASTRO_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "VedAstro API key missing. Set VEDASTRO_API_KEY in environment "
                "or copy .env.example to .env and fill in the key."
            )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "x-api-key": self.api_key,
        }
        self._client = httpx.Client(timeout=timeout, headers=headers)
        self._id = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self):  return self
    def __exit__(self, *a): self.close()

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        r = self._client.post(self.url, json=payload)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"VedAstro error: {data['error']}")
        return data.get("result", {})

    # Convenience wrappers ---------------------------------------------------
    def transits(self, birth_date: str, birth_time: str, lat: float, lon: float, tz: str):
        return self.call("get_current_transits", {
            "birth_date": birth_date, "birth_time": birth_time,
            "latitude": str(lat), "longitude": str(lon), "timezone": tz,
        })

    def current_dasa(self, birth_date: str, birth_time: str, lat: float, lon: float, tz: str,
                     query: str = "current dasa"):
        return self.call("get_current_dasa", {
            "birth_date": birth_date, "birth_time": birth_time,
            "latitude": str(lat), "longitude": str(lon), "timezone": tz,
            "query_text": query,
        })

    def numerology(self, name: str):
        return self.call("get_numerology_prediction", {"name": name})

    def sky_at_date(
        self,
        check_date: str,
        check_time: str = "12:00",
        check_timezone: str = "+00:00",
        query_text: str = "planet positions signs houses",
    ) -> dict[str, Any]:
        """Return planetary positions for an arbitrary date (DD/MM/YYYY format).

        Uses get_context_based_astrology_data with check_* fields so that no
        birth data is required — only the sky at that moment matters.
        """
        return self.call("get_context_based_astrology_data", {
            "check_date": check_date,
            "check_time": check_time,
            "check_timezone": check_timezone,
            "query_text": query_text,
        })

    def natal_chart(
        self,
        birth_date: str,
        birth_time: str,
        lat: float,
        lon: float,
        tz: str,
        query_text: str = (
            "ascendant lagna sign and natal positions of all nine planets "
            "(sun moon mars mercury jupiter venus saturn rahu ketu) "
            "by sign and house"
        ),
    ) -> dict[str, Any]:
        """Fetch natal-chart-level facts (ascendant + planet houses) per person.

        The MCP tool decides which Calculate.* method to invoke based on
        `query_text`. The response evidence typically contains
        `AllPlanetSignsBasedOnHouseLongitudes` and a Lagna/Ascendant entry.
        """
        return self.call("get_context_based_astrology_data", {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "latitude": str(lat),
            "longitude": str(lon),
            "timezone": tz,
            "query_text": query_text,
        })

