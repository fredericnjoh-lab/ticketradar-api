"""
TicketRadar — API de scraping v4
Déployable gratuitement sur Railway ou Render.
Scrape StubHub, SeatGeek, et enrichit ton Google Sheet via l'API Sheets.

INSTALLATION :
  pip install -r requirements.txt

VARIABLES D'ENVIRONNEMENT (à configurer sur Railway/Render) :
  PORT              → port d'écoute (Railway le set automatiquement)
  GOOGLE_SHEET_ID   → ID de ton Sheet (dans l'URL)
  GOOGLE_CREDS_JSON → contenu du fichier credentials.json (service account)

DÉPLOIEMENT RAILWAY :
  1. railway login
  2. railway init
  3. railway up

DÉPLOIEMENT RENDER :
  1. Nouveau Web Service → connecter ce repo GitHub
  2. Build Command : pip install -r requirements.txt
  3. Start Command : python api.py
"""

import os
import json
import time
import re
import asyncio
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TicketRadar Scraper API", version="4.0")

# CORS — autorise ton GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fredericnjoh-lab.github.io",
        "http://localhost:*",
        "*"  # En dev, à restreindre en prod
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Cache en mémoire (évite de scraper trop souvent) ──
CACHE = {}
CACHE_TTL = 3600  # 1 heure

# ── Headers réalistes pour contourner les protections basiques ──
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
}

# ── Prix de revente de référence (fallback si scraping bloqué) ──
REFERENCE_PRICES = {
    "f1 monaco": {"min": 800, "max": 4000, "avg": 2400, "platform": "Viagogo"},
    "f1 abu dhabi": {"min": 450, "max": 2500, "avg": 1475, "platform": "StubHub"},
    "f1 miami": {"min": 600, "max": 2200, "avg": 1400, "platform": "SeatGeek"},
    "f1 silverstone": {"min": 280, "max": 1200, "avg": 740, "platform": "StubHub"},
    "f1 japon": {"min": 400, "max": 1100, "avg": 750, "platform": "Viagogo"},
    "f1 madrid": {"min": 400, "max": 1600, "avg": 1000, "platform": "Viagogo"},
    "ufc las vegas": {"min": 200, "max": 1500, "avg": 850, "platform": "SeatGeek"},
    "nba christmas": {"min": 350, "max": 900, "avg": 625, "platform": "StubHub"},
    "beyonce": {"min": 400, "max": 900, "avg": 650, "platform": "StubHub"},
    "bruno mars": {"min": 350, "max": 900, "avg": 625, "platform": "StubHub"},
    "rosalia": {"min": 130, "max": 250, "avg": 190, "platform": "Viagogo"},
    "tame impala": {"min": 140, "max": 280, "avg": 210, "platform": "Viagogo"},
    "premier league": {"min": 120, "max": 350, "avg": 235, "platform": "StubHub"},
    "orelsan": {"min": 100, "max": 160, "avg": 130, "platform": "Fnac"},
    "gims": {"min": 90, "max": 170, "avg": 130, "platform": "Ticketmaster"},
    "aya nakamura": {"min": 130, "max": 280, "avg": 205, "platform": "Ticketmaster"},
}


# ═══════════════════════════════════════
#  ENDPOINTS
# ═══════════════════════════════════════

@app.get("/")
async def root():
    return {
        "service": "TicketRadar Scraper API",
        "version": "4.0",
        "status": "online",
        "endpoints": ["/prices", "/prices/{event_name}", "/health"]
    }

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/prices")
async def get_all_prices():
    """
    Retourne les prix de revente estimés pour tous les events connus.
    Utilise le cache si disponible, scrape sinon.
    """
    cache_key = "all_prices"
    if cache_key in CACHE:
        ts, data = CACHE[cache_key]
        if time.time() - ts < CACHE_TTL:
            return {"source": "cache", "data": data, "cached_at": ts}

    results = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        for event_key, ref in REFERENCE_PRICES.items():
            # Tente d'abord SeatGeek (API publique la plus accessible)
            live = await scrape_seatgeek(client, event_key)
            if not live:
                # Fallback : prix de référence
                live = ref

            results.append({
                "event_key": event_key,
                "resale_avg": live.get("avg", ref["avg"]),
                "resale_min": live.get("min", ref["min"]),
                "resale_max": live.get("max", ref["max"]),
                "platform": live.get("platform", ref["platform"]),
                "source": "live" if "live" in live else "reference",
                "updated_at": datetime.now().isoformat(),
            })

    CACHE[cache_key] = (time.time(), results)
    return {"source": "live", "data": results}


@app.get("/prices/{event_name}")
async def get_event_price(event_name: str):
    """
    Retourne le prix de revente estimé pour un event spécifique.
    Cherche dans la base de référence + tente un scraping live.
    """
    key = event_name.lower().strip()

    # Cherche dans la base de référence
    ref_price = None
    for ref_key, ref_val in REFERENCE_PRICES.items():
        if ref_key in key or key in ref_key:
            ref_price = ref_val
            break

    # Tente scraping live
    live_price = None
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        live_price = await scrape_seatgeek(client, key)
        if not live_price:
            live_price = await scrape_stubhub(client, key)

    price = live_price or ref_price
    if not price:
        raise HTTPException(status_code=404, detail=f"Aucun prix trouvé pour '{event_name}'")

    return {
        "event": event_name,
        "resale_avg": price.get("avg", 0),
        "resale_min": price.get("min", 0),
        "resale_max": price.get("max", 0),
        "platform": price.get("platform", "N/A"),
        "source": "live" if live_price else "reference",
        "updated_at": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════
#  SCRAPERS
# ═══════════════════════════════════════

async def scrape_seatgeek(client: httpx.AsyncClient, query: str) -> Optional[dict]:
    """
    SeatGeek a une API semi-publique accessible sans clé dans certains cas.
    Sinon, utilise le endpoint public de recherche.
    """
    try:
        # Endpoint de recherche SeatGeek
        url = f"https://seatgeek.com/api/v2/events?q={query.replace(' ', '+')}&per_page=5"
        r = await client.get(url)

        if r.status_code == 200:
            data = r.json()
            events = data.get("events", [])
            if events:
                stats = events[0].get("stats", {})
                avg = stats.get("average_price", 0)
                lo = stats.get("lowest_price", 0)
                hi = stats.get("highest_price", 0)
                if avg > 0:
                    return {"avg": round(avg), "min": round(lo), "max": round(hi), "platform": "SeatGeek", "live": True}

        # Fallback : scraping HTML SeatGeek
        search_url = f"https://seatgeek.com/{query.replace(' ', '-')}-tickets"
        r2 = await client.get(search_url)
        if r2.status_code == 200:
            prices = re.findall(r'\$(\d+)', r2.text)
            prices_int = [int(p) for p in prices if 20 < int(p) < 5000]
            if prices_int:
                return {
                    "avg": round(sum(prices_int) / len(prices_int)),
                    "min": min(prices_int),
                    "max": max(prices_int),
                    "platform": "SeatGeek",
                    "live": True
                }
    except Exception as e:
        print(f"[SeatGeek] Erreur pour '{query}': {e}")

    return None


async def scrape_stubhub(client: httpx.AsyncClient, query: str) -> Optional[dict]:
    """
    Tentative de scraping StubHub.
    StubHub protège agressivement son contenu — résultat non garanti.
    """
    try:
        url = f"https://www.stubhub.com/find/s/?q={query.replace(' ', '+')}"
        r = await client.get(url)

        if r.status_code == 200:
            prices = re.findall(r'\$(\d+(?:\.\d{2})?)', r.text)
            prices_float = [float(p) for p in prices if 20 < float(p) < 5000]
            if prices_float:
                return {
                    "avg": round(sum(prices_float) / len(prices_float)),
                    "min": round(min(prices_float)),
                    "max": round(max(prices_float)),
                    "platform": "StubHub",
                    "live": True
                }
    except Exception as e:
        print(f"[StubHub] Erreur pour '{query}': {e}")

    return None


# ═══════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"TicketRadar API démarrée sur le port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
