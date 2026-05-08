# VedAstro API — Complete Developer Guide

> **Purpose**: Paste this file into any AI chat (ChatGPT, Claude, Gemini, etc.) so the AI can help you build apps using the VedAstro Vedic Astrology API.

---

## What is VedAstro?

VedAstro is an **open-source Vedic astrology platform** providing 596+ astronomical and astrological calculations via a simple REST API. It uses the **Swiss Ephemeris** (NASA JPL data) for high-precision planetary positions and implements classical Vedic astrology algorithms.

- **Website**: https://vedastro.org
- **API Base URL**: `https://api.vedastro.org/api`
- **GitHub**: https://github.com/VedAstro/VedAstro
- **Python Package**: `pip install vedastro`
- **MCP Server**: `https://mcp.vedastro.org/api/mcp`

---

## Pricing

| Tier | Cost | Rate Limit | API Key Required |
|------|------|-----------|-----------------|
| Free | $0 | 5 calls/min | No |
| Premium | $1/month (unlimited) | Unlimited | Yes |

**Subscribe**: https://buy.stripe.com/5kA8y67nVchNdqw4gx

After subscribing, your API key is emailed to you and available at https://vedastro.org/Account.html

---

## Authentication (5 Methods)

All methods work with both POST and GET requests:

```
# 1. x-api-key header (RECOMMENDED)
-H "x-api-key: YOUR_API_KEY"

# 2. APIKey header
-H "APIKey: YOUR_API_KEY"

# 3. Bearer token
-H "Authorization: Bearer YOUR_API_KEY"

# 4. API key in URL path (GET only)
/api/APIKey/YOUR_API_KEY/Calculate/...

# 5. OAuth 2.1 (MCP Server only)
# Claude Desktop and OAuth-capable clients can authenticate via browser.
# OAuth discovery: https://mcp.vedastro.org/.well-known/oauth-protected-resource
```

**Free tier** (no key needed): Limited to 5 requests/minute per IP.

---

## API Methods: POST (Recommended) & GET

### POST Method (Recommended for Apps)

POST is the **recommended method** for all programmatic use. Send a JSON body to:

```
POST https://api.vedastro.org/api/Calculate/{MethodName}
Content-Type: application/json
x-api-key: YOUR_API_KEY
```

**Standard JSON body structure:**

```json
{
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": {
      "Name": "Mumbai",
      "Longitude": 72.8777,
      "Latitude": 19.0760
    }
  },
  "Ayanamsa": "RAMAN"
}
```

### GET Method (Quick Testing Only)

GET is useful for browser testing and simple cURL one-liners. Parameters are encoded in the URL path:

```
GET https://api.vedastro.org/api/Calculate/{MethodName}/Location/{Lat},{Lon}/Time/{HH:MM}/{DD-MM-YYYY}/{+HH:MM}/Ayanamsa/{AyanamsaName}
```

> **Note**: GET uses `-` in dates (`25-10-1992`) while POST uses `/` (`25/10/1992`). GET does not support the "All" bulk keyword.

---

## JSON Data Types Reference

### Time Object
```json
{
  "Time": {
    "StdTime": "HH:MM DD/MM/YYYY +HH:MM",
    "Location": {
      "Name": "City Name",
      "Longitude": 72.8777,
      "Latitude": 19.0760
    }
  }
}
```

### PlanetName
```json
{ "PlanetName": { "Name": "Sun" } }
```
Valid names: `Sun`, `Moon`, `Mars`, `Mercury`, `Jupiter`, `Venus`, `Saturn`, `Rahu`, `Ketu`

Use `"PlanetName": "All"` to get results for all 9 planets at once.

### HouseName
```json
{ "HouseName": "House1" }
```
Valid: `House1` through `House12`

Use `"HouseName": "All"` to get results for all 12 houses at once.

### Ayanamsa (Optional)
```json
{ "Ayanamsa": "RAMAN" }
```
If omitted, defaults to `RAMAN`.

---

## Response Format

All responses follow this structure:

```json
{
  "Status": "Pass",
  "Payload": {
    // ... calculation results ...
  }
}
```

On error:
```json
{
  "Status": "Fail",
  "Payload": "Error message describing what went wrong"
}
```

---

## 6 Calculation Categories

### 1. Horoscope Predictions

Returns 200+ Vedic life predictions based on planetary positions, house placements, and yogas.

**POST** (recommended):
```json
POST /api/Calculate/HoroscopePredictions
{
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN"
}
```

**GET** (quick test):
```
GET /api/Calculate/HoroscopePredictions/Location/19.0760,72.8777/Time/14:30/25-10-1992/+05:30/Ayanamsa/RAMAN
```

**Response**: Array of prediction objects with `Name`, `Description`, `Nature` (Good/Bad/Neutral), and `RelatedBody` (planet/house involved).

### 2. Match/Compatibility Report

Returns a 16-factor Kuta compatibility score between two people.

**POST** (recommended):
```json
POST /api/Calculate/MatchReport
{
  "MaleTime": {
    "StdTime": "08:30 15/06/1990 +05:30",
    "Location": { "Name": "Delhi", "Longitude": 77.21, "Latitude": 28.61 }
  },
  "FemaleTime": {
    "StdTime": "14:20 22/09/1992 -07:00",
    "Location": { "Name": "Los Angeles", "Longitude": -118.24, "Latitude": 34.05 }
  },
  "Ayanamsa": "RAMAN"
}
```

**GET** (quick test):
```
GET /api/Calculate/MatchReport/Location/28.61,77.21/Time/08:30/15-06-1990/+05:30/Location/34.05,-118.24/Time/14:20/22-09-1992/-07:00/Ayanamsa/RAMAN
```

**Response**: Overall Kuta percentage + 16 individual factor scores (Dina, Gana, Mahendra, Stree Deergha, etc.) with Good/Bad ratings and explanations.

### 3. Numerology

Chaldean numerology analysis for any name or number.

**GET** (simple enough for GET):
```
GET /api/Calculate/NameNumberPrediction/Name/John Smith
```

**Response**: Name number, ruling planet, detailed prediction text, and scores for 10 life aspects (Finance, Romance, Education, Health, Family, Growth, Career, Reputation, Spirituality, Luck).

### 4. Raw Planet & House Data

Full astronomical data for all 9 Vedic planets and 12 houses.

**POST — All planets at once** (recommended):
```json
POST /api/Calculate/AllPlanetData
{
  "PlanetName": "All",
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN"
}
```

**POST — Single planet:**
```json
POST /api/Calculate/PlanetRasiD1Sign
{
  "PlanetName": { "Name": "Sun" },
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN"
}
```

**POST — All houses at once:**
```json
POST /api/Calculate/AllHouseData
{
  "HouseName": "All",
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN"
}
```

**Planet data includes**: Sign placement, constellation (nakshatra), house occupied, houses owned, lord details, degrees, retrograde status, speed, dignity (exalted/debilitated).

**House data includes**: Sign, constellation, planets present, lord, aspecting planets.

### 5. General Astro Data

24 key Vedic properties for a birth chart.

**POST** (recommended):
```json
POST /api/Calculate/GeneralAstroData
{
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN"
}
```

**Returns**: Ascendant/Lagna, Moon Sign, Moon Nakshatra, Sunrise/Sunset, Tithi, Karana, Yoga, Weekday Lord, Ayanamsa degree, Kuja Dosha score, and more.

### 6. Ashtakvarga Charts

Sarvashtakavarga and Bhinnashtakavarga tables.

**POST** (recommended):
```json
POST /api/Calculate/AshtakvargaData
{
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN"
}
```

**Returns**: Bindu values (0-8) for each planet in each sign, total Sarvashtakavarga scores, and individual planet contribution tables.

---

## Additional Endpoints

### Dasa Periods (Vimshottari)

```json
POST /api/Calculate/DasaAtRange
{
  "Time": {
    "StdTime": "14:30 25/10/1992 +05:30",
    "Location": { "Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760 }
  },
  "Ayanamsa": "RAMAN",
  "StartTime": "01/01/2024",
  "EndTime": "31/12/2024",
  "Levels": 3
}
```

Returns Mahadasa, Bhukti, and Antaram periods for the given time range.

### List All Available Calculations

```
GET /api/Calculate/ListAllCalls
```

Returns a complete list of all 596+ available calculation methods with their parameter signatures. Use this to discover all available endpoints.

### Divisional Charts

Supports all 16 Shodashavarga divisional charts: D1 (Rasi), D2 (Hora), D3 (Drekkana), D9 (Navamsha), D10 (Dasamsha), D12 (Dwadashamsha), D60 (Shashtiamsha), etc.

---

## Bulk "All" Queries (POST Only)

POST supports the `"All"` keyword to fetch data for all planets or houses in a single request:

```json
// Get ALL planet data in one call
POST /api/Calculate/PlanetRasiD1Sign
{ "PlanetName": "All", "Time": { ... }, "Ayanamsa": "RAMAN" }

// Get ALL house data in one call
POST /api/Calculate/HouseSign
{ "HouseName": "All", "Time": { ... }, "Ayanamsa": "RAMAN" }
```

**Response**: Returns a dictionary keyed by planet/house name with results for each.

---

## Ayanamsa Options

VedAstro supports 47 sidereal ayanamsa systems. Common ones:

| Name | Description |
|------|-------------|
| `RAMAN` | BV Raman's ayanamsa (API default) |
| `LAHIRI` | Lahiri/Chitra Paksha (Indian government standard) |
| `KP` | Krishnamurti Paddhati |
| `FAGAN_BRADLEY` | Fagan-Bradley (Western sidereal) |
| `YUKTESWAR` | Sri Yukteswar |
| `TROPICAL` | No ayanamsa correction (Western tropical) |

Pass in JSON body: `"Ayanamsa": "RAMAN"` or in GET URL: `/Ayanamsa/RAMAN`

---

## Code Examples

### JavaScript / TypeScript (POST — Recommended)

```javascript
const API_KEY = "sk_live_YOUR_KEY";
const BASE = "https://api.vedastro.org/api";

// Horoscope predictions
const response = await fetch(`${BASE}/Calculate/HoroscopePredictions`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-api-key": API_KEY
  },
  body: JSON.stringify({
    Time: {
      StdTime: "14:30 25/10/1992 +05:30",
      Location: { Name: "Mumbai", Longitude: 72.8777, Latitude: 19.0760 }
    },
    Ayanamsa: "RAMAN"
  })
});
const data = await response.json();
console.log(data.Payload);

// Match report
const matchResponse = await fetch(`${BASE}/Calculate/MatchReport`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-api-key": API_KEY
  },
  body: JSON.stringify({
    MaleTime: {
      StdTime: "08:30 15/06/1990 +05:30",
      Location: { Name: "Delhi", Longitude: 77.21, Latitude: 28.61 }
    },
    FemaleTime: {
      StdTime: "14:20 22/09/1992 -07:00",
      Location: { Name: "Los Angeles", Longitude: -118.24, Latitude: 34.05 }
    },
    Ayanamsa: "RAMAN"
  })
});

// All planet data in one call
const planetsResponse = await fetch(`${BASE}/Calculate/AllPlanetData`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-api-key": API_KEY
  },
  body: JSON.stringify({
    PlanetName: "All",
    Time: {
      StdTime: "14:30 25/10/1992 +05:30",
      Location: { Name: "Mumbai", Longitude: 72.8777, Latitude: 19.0760 }
    },
    Ayanamsa: "RAMAN"
  })
});
```

### Python (vedastro library — Recommended)

```python
# pip install vedastro
from vedastro import *

# Set API key (optional, for unlimited access)
Calculate.SetAPIKey('sk_live_YOUR_KEY')

# Create location and time
geo = GeoLocation("Mumbai, India", 72.8777, 19.0760)
birth_time = Time("14:30 25/10/1992 +05:30", geo)

# Horoscope predictions
predictions = Calculate.HoroscopePredictions(birth_time)
Tools.Print(predictions)

# Match compatibility
male_geo = GeoLocation("Delhi", 77.21, 28.61)
male_time = Time("08:30 15/06/1990 +05:30", male_geo)
female_geo = GeoLocation("LA", -118.24, 34.05)
female_time = Time("14:20 22/09/1992 -07:00", female_geo)
report = Calculate.MatchReport(male_time, female_time)
Tools.Print(report)

# Planet data
planet_data = Calculate.AllPlanetData(birth_time)
Tools.Print(planet_data)

# Numerology
numerology = Calculate.NameNumberPrediction("John Smith")
Tools.Print(numerology)
```

### Python (raw HTTP with POST)

```python
import requests
import json

API_KEY = "sk_live_YOUR_KEY"
BASE = "https://api.vedastro.org/api"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": API_KEY
}

# Horoscope predictions
resp = requests.post(f"{BASE}/Calculate/HoroscopePredictions", headers=HEADERS, json={
    "Time": {
        "StdTime": "14:30 25/10/1992 +05:30",
        "Location": {"Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760}
    },
    "Ayanamsa": "RAMAN"
})
print(resp.json()["Payload"])

# Match report
resp = requests.post(f"{BASE}/Calculate/MatchReport", headers=HEADERS, json={
    "MaleTime": {
        "StdTime": "08:30 15/06/1990 +05:30",
        "Location": {"Name": "Delhi", "Longitude": 77.21, "Latitude": 28.61}
    },
    "FemaleTime": {
        "StdTime": "14:20 22/09/1992 -07:00",
        "Location": {"Name": "Los Angeles", "Longitude": -118.24, "Latitude": 34.05}
    },
    "Ayanamsa": "RAMAN"
})
print(resp.json()["Payload"])

# All planets at once
resp = requests.post(f"{BASE}/Calculate/AllPlanetData", headers=HEADERS, json={
    "PlanetName": "All",
    "Time": {
        "StdTime": "14:30 25/10/1992 +05:30",
        "Location": {"Name": "Mumbai", "Longitude": 72.8777, "Latitude": 19.0760}
    },
    "Ayanamsa": "RAMAN"
})
print(resp.json()["Payload"])
```

### cURL (GET — Quick Testing)

```bash
# Horoscope predictions (free tier, no key)
curl "https://api.vedastro.org/api/APIKey/FreeAPIUser/Calculate/HoroscopePredictions/Location/19.0760,72.8777/Time/14:30/25-10-1992/+05:30/Ayanamsa/RAMAN"

# With API key
curl -H "x-api-key: sk_live_YOUR_KEY" \
  "https://api.vedastro.org/api/Calculate/HoroscopePredictions/Location/19.0760,72.8777/Time/14:30/25-10-1992/+05:30/Ayanamsa/RAMAN"

# Numerology (simple enough for GET)
curl "https://api.vedastro.org/api/Calculate/NameNumberPrediction/Name/John%20Smith"
```

---

## MCP Server (AI Integration)

VedAstro provides a Model Context Protocol (MCP) server for direct integration with AI assistants.

**URL**: `https://mcp.vedastro.org/api/mcp`

### Claude Desktop Configuration

Add to your Claude Desktop config file (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "vedastro": {
      "url": "https://mcp.vedastro.org/api/mcp",
      "headers": {
        "x-api-key": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```

### Available MCP Tools

1. **get_horoscope_predictions** — Birth chart life predictions (personality, career, relationships, health, wealth)
2. **get_match_report** — 16-factor Kuta compatibility analysis between two people
3. **get_numerology_prediction** — Chaldean numerology for names, business names, numbers
4. **get_context_based_astrology_data** — Plain-English query + birth data → AI-routed call to the right Calculate method out of 640+ (covers raw planet/house data, ascendant/moon/nakshatra/tithi/yoga, Ashtakvarga, planet strength, and every other per-person lookup)
5. **search_calculate_methods** — Discovery: vector search over 640+ Calculate methods, returns ready-to-call signatures + descriptions

All tools accept birth date (DD/MM/YYYY), time (HH:MM 24h), latitude, longitude, and timezone (+HH:MM).

---

## Python Library Details

**Package**: `vedastro` on PyPI
**Install**: `pip install vedastro`
**GitHub**: https://github.com/VedAstro/VedAstro.Python
**License**: MIT (open source)

The Python library is a thin wrapper around the REST API. All calculations happen server-side (no local computation). This means:
- Always up-to-date with latest algorithms
- Zero heavy dependencies
- Works on any platform with Python 3.6+
- 596+ calculation methods matching the REST API

---

## Building Apps — Quick Start Ideas

Here are some apps you can build with this API:

1. **Horoscope App**: Enter birth details, show life predictions with categorized insights
2. **Marriage Compatibility Checker**: Two birth charts, show Kuta score and detailed analysis
3. **Daily Panchanga Widget**: Show Tithi, Nakshatra, Yoga for any location
4. **Numerology Calculator**: Name analysis with life aspect scores and recommendations
5. **Birth Chart Viewer**: Display planet positions in South/North Indian chart format
6. **Dasa Timeline**: Visual timeline of planetary periods (Mahadasa/Bhukti/Antaram)
7. **Transit Tracker**: Current planetary positions relative to birth chart
8. **AI Astrology Chatbot**: Combine VedAstro MCP with an LLM for conversational astrology

---

## Interactive Tools

- **API Builder** (test endpoints live): https://vedastro.org/APIBuilder.html
- **Account Dashboard** (manage API key): https://vedastro.org/Account.html
- **MCP Server Setup**: https://vedastro.org/MCPServerApp.html
- **Python Library Docs**: https://vedastro.org/PythonVedicAstrologyLibrary.html

---

## Support

- **Email**: contact@vedastro.org
- **WhatsApp**: https://wa.me/message/KKAWK6OXLKHDL1
- **Telegram**: https://t.me/vedastro_org
- **GitHub Issues**: https://github.com/VedAstro/VedAstro/issues

---

## Key Technical Details

- **Calculation Engine**: Swiss Ephemeris (SwissEphNet) — same precision as NASA JPL data
- **Default Ayanamsa**: Raman (API/MCP), Lahiri (some internal calculations)
- **9 Vedic Planets**: Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn, Rahu, Ketu
- **12 Houses**: Full bhava chart with sign lords, aspects, and occupants
- **27 Nakshatras**: Moon constellation system with pada (quarter) calculations
- **Vimshottari Dasa**: Up to 8 levels deep (Mahadasa through PD8)
- **1,077 Astrological Events**: Yogas, planetary combinations, timing events
- **Response Time**: Typically 100-500ms per calculation
- **Uptime**: Hosted on Azure with auto-scaling

---

*Generated from VedAstro.org — The world's most affordable Vedic astrology API*
