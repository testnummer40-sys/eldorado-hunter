"""
Ein-Durchgang-Scraper für GitHub Actions.

Läuft einmal, scraped Elvebredd + Eldorado, schickt für neue Top-Deals
eine Discord-Nachricht an den Webhook aus Env-Variable DISCORD_WEBHOOK.
State (bereits gemeldete URLs) liegt in state.json und wird vom
Workflow zurück ins Repo committed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

import httpx

from models import EldoradoOffer, ElvebreddValue, Deal
from matcher import match_offer_to_value
from scraper import scrape_eldorado, scrape_elvebredd


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("hunter")

STATE_FILE = Path("state.json")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()

ALERT_MULTIPLIER = float(os.environ.get("ALERT_MULTIPLIER", "2.0"))
MIN_DEALS_FOR_MEDIAN = 5
MAX_ALERTS_PER_RUN = 10          # Discord nicht fluten
STATE_TRIM = 2000                 # alte alerted_urls irgendwann vergessen


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"alerted_urls": [], "last_run": None, "last_error": None}


def save_state(state: dict) -> None:
    state["alerted_urls"] = state["alerted_urls"][-STATE_TRIM:]
    STATE_FILE.write_text(json.dumps(state, indent=2))


def build_deals(
    offers: list[EldoradoOffer],
    values: dict[str, ElvebreddValue],
) -> list[Deal]:
    cheapest: dict[tuple[str, str], EldoradoOffer] = {}
    for o in offers:
        k = (o.pet_name.lower(), o.variant)
        c = cheapest.get(k)
        if c is None or o.price_eur < c.price_eur:
            cheapest[k] = o
    deals: list[Deal] = []
    for o in cheapest.values():
        val, score = match_offer_to_value(o, values)
        if val is None:
            continue
        v = val.value_for(o.variant, o.tags)
        if v is None or v <= 0:
            continue
        deals.append(Deal(o, v, v / o.price_eur, score))
    if len(deals) >= MIN_DEALS_FOR_MEDIAN:
        median = statistics.median(d.value_per_eur for d in deals)
        thresh = median * ALERT_MULTIPLIER
        for d in deals:
            d.is_alert = d.value_per_eur >= thresh
    deals.sort(key=lambda d: d.value_per_eur, reverse=True)
    return deals


def send_discord(deal: Deal) -> None:
    if not WEBHOOK:
        log.warning("Kein DISCORD_WEBHOOK gesetzt — überspringe.")
        return
    o = deal.offer
    tags = " ".join(f"`{t}`" for t in o.tags) or "–"
    embed = {
        "title": f"🔥 {o.pet_name} ({o.variant})",
        "url": o.url,
        "color": 0xFF7B72,
        "fields": [
            {"name": "Preis",    "value": f"**{o.price_eur:.2f} €**",      "inline": True},
            {"name": "Value",    "value": f"{deal.value:.3f}",             "inline": True},
            {"name": "Value/€",  "value": f"**{deal.value_per_eur:.2f}**", "inline": True},
            {"name": "Tags",     "value": tags,                             "inline": True},
            {"name": "Seller",   "value": o.seller or "–",                  "inline": True},
            {"name": "Match",    "value": f"{deal.match_score}%",           "inline": True},
        ],
        "footer": {"text": f"Eldorado Hunter · {datetime.now(timezone.utc).strftime('%H:%M UTC')}"},
    }
    try:
        r = httpx.post(WEBHOOK, json={"embeds": [embed]}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.warning("Discord-Webhook fehlgeschlagen: %s", e)


async def main() -> int:
    state = load_state()
    alerted = set(state.get("alerted_urls", []))
    try:
        log.info("Scrape Elvebredd ...")
        values = await scrape_elvebredd()
        log.info("Scrape Eldorado ...")
        offers = await scrape_eldorado()
        deals = build_deals(offers, values)
        log.info("%d Deals, %d Alerts",
                 len(deals), sum(1 for d in deals if d.is_alert))
        new_alerts = [d for d in deals if d.is_alert and d.offer.url not in alerted]
        for d in new_alerts[:MAX_ALERTS_PER_RUN]:
            send_discord(d)
            alerted.add(d.offer.url)
        state["alerted_urls"] = list(alerted)
        state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["last_error"] = None
        state["deals_count"] = len(deals)
        state["alerts_count"] = sum(1 for d in deals if d.is_alert)
        state["new_alerts_sent"] = len(new_alerts[:MAX_ALERTS_PER_RUN])
        save_state(state)
        log.info("OK — %d neue Alerts verschickt.", state["new_alerts_sent"])
        return 0
    except Exception as e:
        log.exception("Fehler")
        state["last_error"] = f"{type(e).__name__}: {e}"
        state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_state(state)
        # Fehler-Ping in Discord (nur 1x pro Fehlertyp)
        last_err_url = f"__error__::{type(e).__name__}"
        if last_err_url not in alerted:
            if WEBHOOK:
                try:
                    httpx.post(WEBHOOK, json={
                        "content": f"⚠️ Scraper-Fehler: `{type(e).__name__}: {e}`"
                    }, timeout=15)
                except Exception:
                    pass
            alerted.add(last_err_url)
            state["alerted_urls"] = list(alerted)
            save_state(state)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
