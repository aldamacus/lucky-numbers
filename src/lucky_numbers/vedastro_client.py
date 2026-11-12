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

    # ── REST API helpers ──────────────────────────────────────────────────────

    REST_BASE = "https://vedastro.zaishi.net/api/Calculate"

    def _rest_post(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST to the VedAstro REST Calculate API.  Returns parsed JSON."""
        url = f"{self.REST_BASE}/{method}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        r = self._client.post(url, json=body, headers=headers)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _std_time(date_ddmmyyyy: str, time_hhmm: str, tz_offset: str,
                  lat: float, lon: float, name: str = "") -> dict[str, Any]:
        """Build the StdTime + Location block used by all REST POST endpoints.

        StdTime format (per Postman collection): "HH:MM DD/MM/YYYY ±HH:MM"
        """
        return {
            "StdTime": f"{time_hhmm} {date_ddmmyyyy} {tz_offset}",
            "Location": {
                "Name": name or f"{lat},{lon}",
                "Latitude": lat,
                "Longitude": lon,
            },
        }

    # ── Public convenience wrappers ───────────────────────────────────────────

    def sky_at_date(
        self,
        check_date: str,
        check_time: str = "12:00",
        check_location_name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Return all planetary sign positions for an arbitrary date.

        Uses REST POST /Calculate/AllPlanetRasiSigns — one call for all 9
        planets.  Returns a GocharaKakshas-shaped dict so the existing
        _normalise_transits / _normalize_transits parsers work unchanged.
        """
        lat = float(latitude or 48.2082)
        lon = float(longitude or 16.3738)
        tz  = timezone or "+01:00"
        loc = check_location_name or ""

        body = {
            "Ayanamsa": "RAMAN",
            "Time": self._std_time(check_date, check_time, tz, lat, lon, loc),
        }
        data = self._rest_post("AllPlanetRasiSigns", body)
        # Response: {"Status":"Pass","Payload":{"Sun":"Capricorn","Moon":"Aries",...}}
        payload = data.get("Payload") or data.get("payload") or {}

        out: dict[str, Any] = {"GocharaKakshas": {}}
        if isinstance(payload, dict):
            for planet, sign_val in payload.items():
                # sign_val may be a string "Capricorn" or {"Name":"Capricorn"}
                sign = sign_val if isinstance(sign_val, str) else (
                    sign_val.get("Name") or sign_val.get("Sign") or
                    sign_val.get("ZodiacSign") or "")
                if sign:
                    out["GocharaKakshas"][planet] = {
                        "ZodiacSign": {"Sign": sign},
                        "Ashtaka": 4, "Sarvashtaka": 4,
                    }
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
        """Fetch natal chart data via REST API.

        Calls two endpoints in parallel:
          1. AllPlanetSignsBasedOnHouseLongitudes — planet signs (birth)
          2. LagnaSignName — ascendant sign

        Returns a structured dict with keys 'planet_signs' and 'lagna_sign'
        that _natal_from_payload() in the UI layer converts into the engine
        natal block.  Falls back to get_horoscope_predictions (MCP) if REST
        calls fail, so legacy parsing path still works.
        """
        lat = float(latitude or 0.0)
        lon = float(longitude or 0.0)
        tz  = timezone or "+00:00"

        time_block = self._std_time(birth_date, birth_time, tz, lat, lon, location_name)
        body = {"Ayanamsa": "RAMAN", "Time": time_block}

        try:
            signs_resp  = self._rest_post("AllPlanetSignsBasedOnHouseLongitudes", body)
            lagna_resp  = self._rest_post("LagnaSignName", body)
            return {
                "_source": "rest",
                "planet_signs": signs_resp.get("Payload") or signs_resp.get("payload") or {},
                "lagna_sign":   (lagna_resp.get("Payload") or lagna_resp.get("payload") or ""),
            }
        except Exception:
            # Fallback: MCP get_horoscope_predictions
            args: dict[str, Any] = {"birth_date": birth_date, "birth_time": birth_time}
            if latitude is not None:
                args["latitude"] = str(latitude)
            if longitude is not None:
                args["longitude"] = str(longitude)
            if timezone is not None:
                args["timezone"] = timezone
            if location_name:
                args["location_name"] = location_name
            return self.call("get_horoscope_predictions", args)

