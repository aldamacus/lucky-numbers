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
    def transits(self, birth_date: str, birth_time: str, location_name: str):
        return self.call("get_current_transits", {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "location_name": location_name,
        })

    def current_dasa(
        self,
        birth_date: str,
        birth_time: str,
        location_name: str,
        query: str = "current dasa",
        check_date: str | None = None,
        check_time: str = "12:00",
        levels: int = 3,
    ):
        from datetime import datetime, timezone

        if check_date is None:
            now = datetime.now(timezone.utc)
            check_date = f"{now.day:02d}/{now.month:02d}/{now.year}"
        return self.call("get_dasa_at_time", {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "location_name": location_name,
            "query_text": query,
            "check_date": check_date,
            "check_time": check_time,
            "levels": levels,
        })

    def numerology(self, name: str):
        return self.call("get_numerology_prediction", {"name": name})

    def sky_at_date(
        self,
        check_date: str,
        check_time: str = "12:00",
        check_location_name: str | None = None,
        query: str = "planet positions signs houses",
    ) -> dict[str, Any]:
        """Return planetary positions for an arbitrary date (DD/MM/YYYY format).

        Uses get_context_based_astrology_data with check_* fields so that no
        birth data is required — only the sky at that moment matters.
        """
        args: dict[str, Any] = {
            "query": query,
            "check_date": check_date,
            "check_time": check_time,
        }
        if check_location_name:
            args["check_location_name"] = check_location_name
        return self.call("get_context_based_astrology_data", args)

    def natal_chart(
        self,
        birth_date: str,
        birth_time: str,
        location_name: str,
        query: str = (
            "ascendant lagna sign and natal positions of all nine planets "
            "(sun moon mars mercury jupiter venus saturn rahu ketu) "
            "by sign and house"
        ),
    ) -> dict[str, Any]:
        """Fetch natal-chart-level facts (ascendant + planet houses) per person.

        The MCP tool decides which Calculate.* method to invoke based on
        `query`. The response evidence typically contains
        `AllPlanetSignsBasedOnHouseLongitudes` and a Lagna/Ascendant entry.
        """
        return self.call("get_context_based_astrology_data", {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "location_name": location_name,
            "query": query,
        })

