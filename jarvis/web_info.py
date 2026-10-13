"""Free web lookups: DuckDuckGo search and Open-Meteo weather (no API keys)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx

DDG_URL = "https://html.duckduckgo.com/html/"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36"

WMO = {
    0: "vedro", 1: "pretežno vedro", 2: "delimično oblačno", 3: "oblačno", 45: "magla", 48: "magla sa injem",
    51: "slaba rosulja", 53: "rosulja", 55: "jaka rosulja", 61: "slaba kiša", 63: "kiša", 65: "jaka kiša",
    66: "ledena kiša", 67: "jaka ledena kiša", 71: "slab sneg", 73: "sneg", 75: "jak sneg", 77: "sneg u zrnima",
    80: "pljuskovi", 81: "jaki pljuskovi", 82: "olujni pljuskovi", 85: "snežni pljuskovi", 86: "jaki snežni pljuskovi",
    95: "grmljavina", 96: "grmljavina sa gradom", 99: "jaka grmljavina sa gradom",
}
DAYS = ["pon", "uto", "sre", "čet", "pet", "sub", "ned"]


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def _clean(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _real_url(href: str) -> str:
    href = html.unescape(href)
    if "duckduckgo.com/l/" in href:
        q = parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
        if "uddg" in q:
            return unquote(q["uddg"][0])
    return href


def parse_ddg(page: str, limit: int = 5) -> list[SearchResult]:
    results = []
    blocks = re.split(r'<div class="result results_links', page)[1:]
    for b in blocks:
        a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not a:
            continue
        sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', b, re.S)
        if 'result--ad' in b[:200]:
            continue
        results.append(SearchResult(_clean(a.group(2)), _real_url(a.group(1)), _clean(sn.group(1)) if sn else ""))
        if len(results) >= limit:
            break
    return results


class WebInfo:
    def __init__(self, lat: float, lon: float, tz: str, city: str, client: httpx.AsyncClient | None = None):
        self.lat, self.lon, self.tz, self.city = lat, lon, tz, city
        self.http = client or httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}, follow_redirects=True)

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        resp = await self.http.post(DDG_URL, data={"q": query, "kl": "rs-sr"})
        resp.raise_for_status()
        return parse_ddg(resp.text, limit)

    async def weather_data(self) -> dict:
        resp = await self.http.get(WEATHER_URL, params={
            "latitude": self.lat, "longitude": self.lon, "timezone": self.tz, "forecast_days": 4,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        })
        resp.raise_for_status()
        return resp.json()

    async def weather_text(self, days: int = 1) -> str:
        return format_weather(await self.weather_data(), self.city, days)

    async def aclose(self) -> None:
        await self.http.aclose()


def format_weather(d: dict, city: str, days: int = 1) -> str:
    from datetime import date

    c = d.get("current", {})
    lines = [
        f"{city}: {round(c.get('temperature_2m', 0))}°C (oseća se {round(c.get('apparent_temperature', 0))}°C), "
        f"{WMO.get(c.get('weather_code'), 'nepoznato')}, vetar {round(c.get('wind_speed_10m', 0))} km/h"
    ]
    daily = d.get("daily", {})
    for i, day in enumerate(daily.get("time", [])[: max(1, days)]):
        name = "danas" if i == 0 else ("sutra" if i == 1 else DAYS[date.fromisoformat(day).weekday()])
        lines.append(
            f"{name}: {round(daily['temperature_2m_min'][i])}–{round(daily['temperature_2m_max'][i])}°C, "
            f"{WMO.get(daily['weather_code'][i], '?')}, kiša {daily['precipitation_probability_max'][i] or 0}%"
        )
    return "\n".join(lines)
