"""
TicketRadar — API de scraping v4 + Bot Telegram
"""

import os
import json
import time
import re
import asyncio
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TicketRadar Scraper API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Config Telegram ──
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8661432122:AAHbSAbpjTZceBKIM0CBjjMNMlpJp48mzQw_botfather")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "170104619")

# ── Cache ──
CACHE = {}
CACHE_TTL = 3600
NOTIFIED_KEYS = set()

# ── Headers ──
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
}

# ── Prix de référence ──
REFERENCE_PRICES = {
    "f1 monaco":        {"min": 800,  "max": 4000, "avg": 2400, "platform": "Viagogo"},
    "f1 abu dhabi":     {"min": 450,  "max": 2500, "avg": 1475, "platform": "StubHub"},
    "f1 miami":         {"min": 600,  "max": 2200, "avg": 1400, "platform": "SeatGeek"},
    "f1 silverstone":   {"min": 280,  "max": 1200, "avg": 740,  "platform": "StubHub"},
    "f1 japon":         {"min": 400,  "max": 1100, "avg": 750,  "platform": "Viagogo"},
    "f1 madrid":        {"min": 400,  "max": 1600, "avg": 1000, "platform": "Viagogo"},
    "ufc las vegas":    {"min": 200,  "max": 1500, "avg": 850,  "platform": "SeatGeek"},
    "nba christmas":    {"min": 350,  "max": 900,  "avg": 625,  "platform": "StubHub"},
    "beyonce":          {"min": 400,  "max": 900,  "avg": 650,  "platform": "StubHub"},
    "bruno mars":       {"min": 350,  "max": 900,  "avg": 625,  "platform": "StubHub"},
    "rosalia":          {"min": 130,  "max": 250,  "avg": 190,  "platform": "Viagogo"},
    "tame impala":      {"min": 140,  "max": 280,  "avg": 210,  "platform": "Viagogo"},
    "coachella":        {"min": 800,  "max": 2000, "avg": 1409, "platform": "StubHub"},
    "champions league": {"min": 400,  "max": 2500, "avg": 1800, "platform": "StubHub"},
    "wimbledon":        {"min": 875,  "max": 9495, "avg": 2800, "platform": "Viagogo"},
    "premier league":   {"min": 120,  "max": 350,  "avg": 235,  "platform": "StubHub"},
    "orelsan":          {"min": 100,  "max": 160,  "avg": 130,  "platform": "Fnac"},
    "world cup":        {"min": 410,  "max": 3500, "avg": 1200, "platform": "StubHub"},
    "ariana grande":    {"min": 200,  "max": 600,  "avg": 380,  "platform": "StubHub"},
    "sabrina carpenter":{"min": 180,  "max": 600,  "avg": 420,  "platform": "SeatGeek"},
}

# ══════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════

async def send_telegram(message: str):
    """Envoie un message Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Token ou Chat ID manquant")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                print(f"[Telegram] ✓ Message envoyé")
                return True
            else:
                print(f"[Telegram] Erreur {r.status_code}: {r.text}")
                return False
    except Exception as e:
        print(f"[Telegram] Exception: {e}")
        return False

async def check_and_alert(events: list, seuil: int = 30):
    """Vérifie les events et envoie des alertes Telegram si marge > seuil."""
    global NOTIFIED_KEYS
    hits = []
    for ev in events:
        try:
            face   = float(ev.get("face", 0))
            resale = float(ev.get("resale", 0))
            if face <= 0 or resale <= 0:
                continue
            net   = resale * 0.85
            marge = round(((net - face) / face) * 100)
            ev["marge_calc"] = marge
            if marge >= seuil:
                hits.append(ev)
        except:
            continue

    hits.sort(key=lambda x: x.get("marge_calc", 0), reverse=True)

    for ev in hits:
        key = f"{ev.get('name','')}_{ev.get('marge_calc',0)}"
        if key in NOTIFIED_KEYS:
            continue

        name     = ev.get("name", "Event inconnu")
        flag     = ev.get("flag", "🎫")
        marge    = ev.get("marge_calc", 0)
        face_v   = ev.get("face", "?")
        resale_v = ev.get("resale", "?")
        date_v   = ev.get("date", "")
        platform = ev.get("platform", "")

        msg = (
            f"🔥 <b>TicketRadar — Nouvelle opportunité !</b>\n\n"
            f"{flag} <b>{name}</b>\n"
            f"💰 Marge : <b>+{marge}%</b>\n"
            f"🎫 Face : {face_v}€ → Revente : {resale_v}€\n"
            f"📅 {date_v}\n"
            f"🏪 {platform}\n"
            f"⚡ Seuil dépassé : +{seuil}%\n\n"
            f"👉 <a href='https://fredericnjoh-lab.github.io/ticketradar/'>Voir l'opportunité</a>"
        )

        sent = await send_telegram(msg)
        if sent:
            NOTIFIED_KEYS.add(key)
            # Garde max 500 keys en mémoire
            if len(NOTIFIED_KEYS) > 500:
                NOTIFIED_KEYS = set(list(NOTIFIED_KEYS)[-200:])

    return len(hits)

# ══════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "service": "TicketRadar Scraper API",
        "version": "4.0",
        "status": "online",
        "telegram": "configured" if TELEGRAM_TOKEN else "not configured",
        "endpoints": ["/prices", "/prices/{event_name}", "/health", "/alert/test", "/alert/scan"]
    }

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/alert/test")
async def test_alert():
    """Envoie une notification Telegram de test."""
    msg = (
        "🧪 <b>TicketRadar — Test de connexion</b>\n\n"
        "✅ Ton bot Telegram est bien connecté !\n"
        "Tu recevras ici les alertes dès qu'une opportunité dépasse ton seuil.\n\n"
        "🇲🇨 <b>Exemple : F1 GP Monaco</b>\n"
        "💰 Marge : <b>+167%</b>\n"
        "🎫 900€ → 2 400€\n\n"
        "👉 <a href='https://fredericnjoh-lab.github.io/ticketradar/'>Ouvrir TicketRadar</a>"
    )
    success = await send_telegram(msg)
    return {
        "success": success,
        "message": "Notification test envoyée !" if success else "Erreur — vérifie TELEGRAM_TOKEN et TELEGRAM_CHAT_ID"
    }

@app.get("/alert/scan")
async def alert_scan(seuil: int = 30, sheet_url: str = ""):
    """
    Scanne le Google Sheet et envoie des alertes pour les opportunités > seuil.
    Appelle : /alert/scan?seuil=30&sheet_url=TON_URL_CSV
    """
    if not sheet_url:
        return {"error": "sheet_url requis", "example": "/alert/scan?seuil=30&sheet_url=https://docs.google.com/..."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(sheet_url + "&cache=" + str(int(time.time())))
            if not r.ok:
                return {"error": f"HTTP {r.status_code}"}
            text = r.text

        events = parse_csv(text)
        if not events:
            return {"error": "Sheet vide ou format incorrect"}

        alerts_sent = await check_and_alert(events, seuil)
        return {
            "events_scanned": len(events),
            "alerts_sent": alerts_sent,
            "seuil": seuil,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/prices")
async def get_all_prices():
    cache_key = "all_prices"
    if cache_key in CACHE:
        ts, data = CACHE[cache_key]
        if time.time() - ts < CACHE_TTL:
            return {"source": "cache", "data": data}

    results = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        for event_key, ref in REFERENCE_PRICES.items():
            live = await scrape_seatgeek(client, event_key)
            if not live:
                live = ref
            results.append({
                "event_key":   event_key,
                "resale_avg":  live.get("avg",      ref["avg"]),
                "resale_min":  live.get("min",      ref["min"]),
                "resale_max":  live.get("max",      ref["max"]),
                "platform":    live.get("platform", ref["platform"]),
                "source":      "live" if "live" in live else "reference",
                "updated_at":  datetime.now().isoformat(),
            })

    CACHE[cache_key] = (time.time(), results)
    return {"source": "live", "data": results}

@app.get("/prices/{event_name}")
async def get_event_price(event_name: str):
    key = event_name.lower().strip()
    ref_price = None
    for ref_key, ref_val in REFERENCE_PRICES.items():
        if ref_key in key or key in ref_key:
            ref_price = ref_val
            break

    live_price = None
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        live_price = await scrape_seatgeek(client, key)

    price = live_price or ref_price
    if not price:
        return {"error": f"Aucun prix trouvé pour '{event_name}'"}

    return {
        "event":       event_name,
        "resale_avg":  price.get("avg", 0),
        "resale_min":  price.get("min", 0),
        "resale_max":  price.get("max", 0),
        "platform":    price.get("platform", "N/A"),
        "source":      "live" if live_price else "reference",
        "updated_at":  datetime.now().isoformat(),
    }

# ══════════════════════════════════════════
#  SCRAPERS
# ══════════════════════════════════════════

async def scrape_seatgeek(client: httpx.AsyncClient, query: str) -> Optional[dict]:
    try:
        url = f"https://seatgeek.com/api/v2/events?q={query.replace(' ', '+')}&per_page=5"
        r = await client.get(url)
        if r.status_code == 200:
            data = r.json()
            events = data.get("events", [])
            if events:
                stats = events[0].get("stats", {})
                avg = stats.get("average_price", 0)
                lo  = stats.get("lowest_price",  0)
                hi  = stats.get("highest_price", 0)
                if avg > 0:
                    return {"avg": round(avg), "min": round(lo), "max": round(hi), "platform": "SeatGeek", "live": True}
    except Exception as e:
        print(f"[SeatGeek] Erreur pour '{query}': {e}")
    return None

# ══════════════════════════════════════════
#  CSV PARSER
# ══════════════════════════════════════════

def parse_csv(text: str) -> list:
    lines = text.strip().split('\n')
    if len(lines) < 2:
        return []
    headers = split_csv_line(lines[0])
    headers = [h.strip().replace('"', '').lower() for h in headers]
    result = []
    for line in lines[1:]:
        cols = split_csv_line(line)
        row = {}
        for i, h in enumerate(headers):
            row[h] = (cols[i] if i < len(cols) else '').replace('"', '').strip()
        if row.get('name'):
            result.append(row)
    return result

def split_csv_line(line: str) -> list:
    result, current, in_quotes = [], '', False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == ',' and not in_quotes:
            result.append(current)
            current = ''
        else:
            current += char
    result.append(current)
    return result

# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"TicketRadar API + Bot Telegram démarrés sur le port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
