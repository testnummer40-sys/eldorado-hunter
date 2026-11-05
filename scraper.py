"""
Scraping-Logik für Eldorado.gg und Elvebredd.com.

v2: korrigierte Elvebredd-URL (/calculator statt /pet-value-calculator),
längere Wartezeiten und mehrere Selektor-Strategien.

Falls Elvebredd weiterhin streikt, gibt scrape_elvebredd einen
RuntimeError mit einem Snippet der Seite — der landet in Discord
und wir können sehen, welchen Selektor die Seite tatsächlich nutzt.
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
ELVEBREDD_URL = "https://elvebredd.com/calculator"

PRICE_MIN_EUR = 0.02
PRICE_MAX_EUR = 30.0


# ---------------------------------------------------------------------------
# Browser-Helfer
# ---------------------------------------------------------------------------
async def _make_browser(pw) -> Browser:
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
    await ctx.add_init_script(
        """Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"""
    )
    return await ctx.new_page()


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
# Elvebredd
# ---------------------------------------------------------------------------
async def scrape_elvebredd() -> dict[str, ElvebreddValue]:
    """
    Zieht alle Pet-Werte von elvebredd.com/calculator.

    Strategie:
      1) Seite laden, 30 s auf JS warten, bis irgendein Pet-Bild/Name da ist
      2) Autocomplete-Suche öffnen (suche nach "a"), Vorschläge einsammeln
      3) Falls Suchfeld-Strategie nichts bringt: alle Elemente einsammeln,
         die wie Pet-Karten aussehen (Bild + Zahl)
      4) Bei komplettem Fehlschlag: RuntimeError mit Seiten-Snippet werfen
    """
    values: dict[str, ElvebreddValue] = {}
    snippet = ""
    async with async_playwright() as pw:
        browser = await _make_browser(pw)
        try:
            page = await _new_page(browser)
            await page.goto(ELVEBREDD_URL, wait_until="domcontentloaded", timeout=60_000)

            # Cookie/Overlay wegklicken
            for sel in (
                "button:has-text('Accept')",
                "button:has-text('Akzeptieren')",
                "button:has-text('I agree')",
                "button:has-text('Got it')",
                "[aria-label='Close']",
            ):
                try:
                    await page.locator(sel).first.click(timeout=2000)
                except Exception:
                    pass

            # Warte auf irgendeine Pet-Komponente (sehr generisch)
            try:
                await page.wait_for_function(
                    """() => {
                      // Suche nach irgendeinem Element, dessen Text wie ein Pet-Name aussieht
                      // und das Zahlen in der Nähe hat
                      const text = document.body.innerText;
                      return text.length > 2000 &&
                             (text.includes('Dragon') || text.includes('Unicorn') ||
                              text.includes('Griffin') || text.includes('Dog'));
                    }""",
                    timeout=30_000,
                )
            except Exception:
                pass  # trotzdem weiterprobieren

            # Zusätzlich 5 s warten, dass alle Daten kommen
            await asyncio.sleep(5)

            # --- Strategie A: Großer Fetch aller "Pet-Karten" ---
            # Elvebredd rendert oft Karten mit <img alt="Pet Name"> + Zahl daneben
            rows = await page.evaluate(
                """() => {
                  const out = [];
                  // Alle Bilder mit alt-Text sammeln
                  document.querySelectorAll('img[alt]').forEach(img => {
                    const alt = (img.alt || '').trim();
                    if (!alt || alt.length < 3 || alt.length > 40) return;
                    if (/logo|icon|user|avatar|arrow/i.test(alt)) return;
                    // Finde Container und schnapp dir den Text
                    let el = img.parentElement;
                    for (let i = 0; i < 4 && el; i++) {
                      const txt = (el.innerText || '').trim();
                      // Suche nach einer Zahl im Text
                      const nums = txt.match(/\\d+(?:[\\.,]\\d+)?/g);
                      if (nums && nums.length >= 1) {
                        out.push({ name: alt, text: txt.slice(0, 200) });
                        return;
                      }
                      el = el.parentElement;
                    }
                  });
                  return out;
                }"""
            )

            for r in rows:
                name = r["name"].strip()
                nums = [float(x.replace(",", ".")) for x in
                        re.findall(r"\d+(?:[\.,]\d+)?", r["text"])]
                if not nums:
                    continue
                # Erster Wert = normal, zweiter = neon, dritter = mega
                values[name] = ElvebreddValue(
                    pet_name=name,
                    normal=nums[0] if len(nums) > 0 else None,
                    neon=nums[1] if len(nums) > 1 else None,
                    mega_neon=nums[2] if len(nums) > 2 else None,
                )

            # --- Falls A nichts bringt: alten Tabellen-Parser als Fallback ---
            if not values:
                table_rows = await page.evaluate(
                    """() => {
                      const out = [];
                      document.querySelectorAll('table tr').forEach(tr => {
                        const cells = [...tr.querySelectorAll('td, th')].map(c => c.innerText.trim());
                        if (cells.length >= 2) out.push(cells);
                      });
                      return out;
                    }"""
                )
                for cells in table_rows:
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

            # Falls IMMER NOCH nichts: Snippet für Debug sammeln
            if not values:
                snippet = (await page.inner_text("body"))[:600]
                html_head = (await page.content())[:400]
                raise RuntimeError(
                    f"Elvebredd: keine Werte erkannt.\n"
                    f"URL: {page.url}\n"
                    f"Body-Snippet: {snippet[:400]!r}\n"
                    f"HTML-Head: {html_head!r}"
                )
        finally:
            await browser.close()

    log.info("Elvebredd: %d Werte geladen", len(values))
    return values


# ---------------------------------------------------------------------------
# Eldorado
# ---------------------------------------------------------------------------
async def scrape_eldorado(max_pages: int = 10) -> list[EldoradoOffer]:
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

                if "cf-chl" in (await page.content()).lower()[:5000]:
                    log.warning("Cloudflare-Challenge auf Seite %d — warte...", p)
                    await asyncio.sleep(8)

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
                        const priceMatch = txt.match(/([0-9]+(?:[.,][0-9]+)?)\\s*(?:€|EUR)/i);
                        const price = priceMatch ? parseFloat(priceMatch[1].replace(',', '.')) : null;
                        const sellerMatch = txt.match(/by\\s+([A-Za-z0-9_\\-]+)/i);
                        const seller = sellerMatch ? sellerMatch[1] : '';
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
                await asyncio.sleep(1.2)
        finally:
            await browser.close()

    log.info("Eldorado: %d Angebote geladen", len(offers))
    return offers
