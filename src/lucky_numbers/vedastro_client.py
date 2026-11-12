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
    def transits(
        self,
        birth_date: str,
        birth_time: str,
        location_name: str,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str | None = None,
    ):
        args: dict[str, Any] = {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "location_name": location_name,
        }
        # New API (vedastro.zaishi.net) requires explicit coords + timezone
        if latitude is not None:
            args["latitude"] = str(latitude)
        if longitude is not None:
            args["longitude"] = str(longitude)
        if timezone is not None:
            args["timezone"] = timezone
        return self.call("get_current_transits", args)

    def current_dasa(
        self,
        birth_date: str,
        birth_time: str,
        location_name: str,
        query: str = "current dasa",
        check_date: str | None = None,
        check_time: str = "12:00",
        levels: int = 3,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str | None = None,
    ):
        from datetime import datetime, timezone as _tz

        if check_date is None:
            now = datetime.now(_tz.utc)
            check_date = f"{now.day:02d}/{now.month:02d}/{now.year}"
        args: dict[str, Any] = {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "location_name": location_name,
            "query_text": query,
            "check_date": check_date,
            "check_time": check_time,
            "levels": levels,
        }
        # New API (vedastro.zaishi.net) requires explicit coords + timezone
        if latitude is not None:
            args["latitude"] = str(latitude)
        if longitude is not None:
            args["longitude"] = str(longitude)
        if timezone is not None:
            args["timezone"] = timezone
        return self.call("get_dasa_at_time", args)

    def numerology(self, name: str):
        return self.call("get_numerology_prediction", {"name": name})

    def sky_at_date(
        self,
        check_date: str,
        check_time: str = "12:00",
        check_location_name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Return planetary positions for an arbitrary past/future date.

        get_context_based_astrology_data was removed from the new MCP server.
        Falls back to the VedAstro REST API (vedastro.zaishi.net) to fetch
        planet signs for each of the 9 Vedic planets via direct HTTP calls.
        Returns a dict shaped like a GocharaKakshas payload so the existing
        _normalise_transits / _normalize_transits parsers continue to work.
        """
        REST_BASE = "https://vedastro.zaishi.net/api/Calculate"
        PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                   "Venus", "Saturn", "Rahu", "Ketu"]

        lat = latitude or 48.2082
        lon = longitude or 16.3738
        tz  = timezone  or "+01:00"

        # REST URL format: /Location/{lat},{lon}/Time/{HH:MM}/{DD-MM-YYYY}/{tz}/Ayanamsa/RAMAN
        # check_date arrives as DD/MM/YYYY — convert separators to DD-MM-YYYY
        date_dashes = check_date.replace("/", "-")
        loc_seg = f"{lat},{lon}"
        time_seg = f"{check_time}/{date_dashes}/{tz}"

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        out: dict[str, Any] = {"GocharaKakshas": {}}
        for planet in PLANETS:
            url = f"{REST_BASE}/{planet}SignName/Location/{loc_seg}/Time/{time_seg}/Ayanamsa/RAMAN"
            try:
                r = self._client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
                # REST API returns {"Status":"Pass","Payload":"Sagittarius",...}
                sign = (data.get("Payload") or data.get("payload") or
                        data.get("Result") or "").strip()
                if sign:
                    out["GocharaKakshas"][planet] = {
                        "ZodiacSign": {"Sign": sign},
                        "Ashtaka": 4, "Sarvashtaka": 4,  # placeholder scores
                    }
            except Exception:
                pass  # silently skip unavailable planets

        return out

    def natal_chart(
        self,
        birth_date: str,
        birth_time: str,
        location_name: str,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Fetch natal-chart horoscope predictions.

        get_context_based_astrology_data was removed from the new MCP server.
        Now uses get_horoscope_predictions — the prediction Name fields encode
        planet/house info (e.g. 'JupiterIn10House', 'LagnaInScorpio') which
        _natal_from_payload() in the UI layer parses into the engine-friendly
        natal block.
        """
        args: dict[str, Any] = {
            "birth_date": birth_date,
            "birth_time": birth_time,
        }
        if latitude is not None:
            args["latitude"] = str(latitude)
        if longitude is not None:
            args["longitude"] = str(longitude)
        if timezone is not None:
            args["timezone"] = timezone
        if location_name:
            args["location_name"] = location_name
        return self.call("get_horoscope_predictions", args)

