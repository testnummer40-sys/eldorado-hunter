"""
Scraping-Logik für Eldorado.gg und Elvebredd.com.

Beide Seiten rendern Werte per JavaScript, daher nutzen wir Playwright.
Eldorado hat zusätzlich Cloudflare — wir setzen daher einen echten Browser
mit Stealth-Einstellungen ein.

Selektoren können sich jederzeit ändern. Die Scraper geben bei Fehlern
sprechende Meldungen zurück, damit du siehst, WAS angepasst werden muss.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser

from models import EldoradoOffer, ElvebreddValue
from matcher import parse_title


log = logging.getLogger("scraper")

ELDORADO_URL = "https://www.eldorado.gg/adopt-me-pets/i/201-2-0"
ELVEBREDD_URL = "https://elvebredd.com/pet-value-calculator"

# Preis-Grenzen (EUR)
PRICE_MIN_EUR = 0.02
PRICE_MAX_EUR = 30.0


# ---------------------------------------------------------------------------
# Browser-Helfer
# ---------------------------------------------------------------------------
async def _make_browser(pw) -> Browser:
    """Startet Chromium mit stealth-artigen Einstellungen."""
    return await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )


async def _new_page(browser: Browser) -> Page:
    ctx = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 850},
        locale="de-DE",
    )
    # verstecken, dass wir headless sind
    await ctx.add_init_script(
        """Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"""
    )
    return await ctx.new_page()


# ---------------------------------------------------------------------------
# Elvebredd-Werte
# ---------------------------------------------------------------------------
async def scrape_elvebredd() -> dict[str, ElvebreddValue]:
    """
    Zieht alle Pet-Werte von elvebredd.com/pet-value-calculator.

    Die Seite rendert eine große Tabelle; Spalten:
      Pet | Normal | Neon | Mega Neon
    Wir warten, bis die Tabelle da ist, und parsen die Zeilen.
    """
    values: dict[str, ElvebreddValue] = {}
    async with async_playwright() as pw:
        browser = await _make_browser(pw)
        try:
            page = await _new_page(browser)
            await page.goto(ELVEBREDD_URL, wait_until="networkidle", timeout=60_000)
            # Cookie/Overlay wegklicken, falls vorhanden
            for sel in ("button:has-text('Accept')", "button:has-text('Akzeptieren')"):
                try:
                    await page.locator(sel).first.click(timeout=2000)
                except Exception:
                    pass

            # Warte auf eine Tabelle/Grid mit Pet-Daten
            # Falls Elvebredd anders rendert: Selektor hier anpassen.
            await page.wait_for_selector(
                "table, [role='row'], .pet-row, .value-row",
                timeout=20_000,
            )

            rows = await page.evaluate(
                """() => {
                  const out = [];
                  // Strategie 1: echte <tr>-Tabelle
                  document.querySelectorAll('table tr').forEach(tr => {
                    const cells = [...tr.querySelectorAll('td, th')].map(c => c.innerText.trim());
                    if (cells.length >= 2) out.push(cells);
                  });
                  // Strategie 2: Grid mit role=row
                  if (out.length === 0) {
                    document.querySelectorAll('[role=row]').forEach(r => {
                      const cells = [...r.querySelectorAll('[role=cell], [role=columnheader]')]
                        .map(c => c.innerText.trim());
                      if (cells.length >= 2) out.push(cells);
                    });
                  }
                  return out;
                }"""
            )

            for cells in rows:
                name = cells[0].strip()
                if not name or name.lower().startswith(("pet", "name")):
                    continue
                nums = [_to_float(c) for c in cells[1:4]]
                if all(v is None for v in nums):
                    continue
                values[name] = ElvebreddValue(
                    pet_name=name,
                    normal=nums[0] if len(nums) > 0 else None,
                    neon=nums[1] if len(nums) > 1 else None,
                    mega_neon=nums[2] if len(nums) > 2 else None,
                )
        finally:
            await browser.close()

    log.info("Elvebredd: %d Werte geladen", len(values))
    return values


def _to_float(s: str) -> Optional[float]:
    if not s:
        return None
    m = re.search(r"[-+]?\d*[\.,]?\d+", s.replace(",", "."))
    if not m:
        return None
    try:
        return float(m.group().replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Eldorado-Angebote
# ---------------------------------------------------------------------------
async def scrape_eldorado(max_pages: int = 10) -> list[EldoradoOffer]:
    """
    Zieht alle Adopt-Me-Angebote im Preisbereich 0.02 – 30 EUR von Eldorado.

    Eldorado unterstützt Preisfilter über Query-Parameter. Wir wandern
    durch die Seiten, bis entweder keine Angebote mehr da sind oder
    max_pages erreicht ist.
    """
    offers: list[EldoradoOffer] = []
    async with async_playwright() as pw:
        browser = await _make_browser(pw)
        try:
            page = await _new_page(browser)
            for p in range(1, max_pages + 1):
                url = (
                    f"{ELDORADO_URL}?priceMin={PRICE_MIN_EUR}"
                    f"&priceMax={PRICE_MAX_EUR}&page={p}&sort=price_asc"
                )
                try:
                    await page.goto(url, wait_until="networkidle", timeout=60_000)
                except Exception as e:
                    log.warning("Eldorado Seite %d nicht erreichbar: %s", p, e)
                    break

                # Cloudflare-Check: Gibt's eine Challenge?
                if "cf-chl" in (await page.content()).lower()[:5000]:
                    log.warning("Cloudflare-Challenge auf Seite %d — warte...", p)
                    await asyncio.sleep(8)

                # Warte auf Angebotskarten.
                # Selektoren hier evtl. anpassen, falls Eldorado redesigned.
                try:
                    await page.wait_for_selector(
                        "a[href*='/offer/'], [data-testid='offer-card'], .offer-card",
                        timeout=15_000,
                    )
                except Exception:
                    log.info("Keine Angebote auf Seite %d — Ende.", p)
                    break

                items = await page.evaluate(
                    """() => {
                      const cards = document.querySelectorAll(
                        "a[href*='/offer/'], [data-testid='offer-card'], .offer-card"
                      );
                      const seen = new Set();
                      const out = [];
                      cards.forEach(card => {
                        const link = card.closest('a') || card.querySelector('a');
                        const href = link ? link.href : '';
                        if (!href || seen.has(href)) return;
                        seen.add(href);
                        const txt = card.innerText || '';
                        // Preis: suche € oder EUR
                        const priceMatch = txt.match(/([0-9]+(?:[.,][0-9]+)?)\\s*(?:€|EUR)/i);
                        const price = priceMatch ? parseFloat(priceMatch[1].replace(',', '.')) : null;
                        // Verkäufer: oft 'by XYZ' oder zweite Textzeile
                        const sellerMatch = txt.match(/by\\s+([A-Za-z0-9_\\-]+)/i);
                        const seller = sellerMatch ? sellerMatch[1] : '';
                        // Titel: erste nicht-leere Zeile
                        const title = (txt.split('\\n').map(s=>s.trim()).filter(Boolean)[0]) || '';
                        out.push({href, title, price, seller});
                      });
                      return out;
                    }"""
                )

                if not items:
                    break

                for it in items:
                    price = it.get("price")
                    if price is None or not (PRICE_MIN_EUR <= price <= PRICE_MAX_EUR):
                        continue
                    title = it.get("title") or ""
                    pet, variant, tags = parse_title(title)
                    if not pet:
                        continue
                    offers.append(EldoradoOffer(
                        pet_name=pet,
                        variant=variant,
                        tags=tags,
                        price_eur=float(price),
                        seller=it.get("seller") or "unknown",
                        url=it.get("href") or "",
                        raw_title=title,
                    ))
                await asyncio.sleep(1.2)  # höflich sein
        finally:
            await browser.close()

    log.info("Eldorado: %d Angebote geladen", len(offers))
    return offers
