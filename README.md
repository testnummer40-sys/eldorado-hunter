# 🐾 Eldorado Hunter — Discord-Version

Alle 15 Min. durchsucht ein GitHub-Action die Adopt-Me-Angebote auf
Eldorado (0,02 – 30 €), rechnet sie gegen die Elvebredd-Values und
pingt dich per Discord-Webhook bei jedem **besonders günstigen** Deal
(Value/€ ≥ Median × 2).

- **Komplett gratis** (öffentliches GitHub-Repo = unbegrenzte Minuten).
- Setup komplett vom Handy machbar.
- Dein Handy bekommt die Alerts als normale **Discord-Push-Benachrichtigung**.

## Setup (einmalig, ca. 15 Min, alles am Handy)

### 1. GitHub-Account
Auf **github.com/signup** einen Account anlegen (gratis).

### 2. Dieses Repo hochladen
1. Auf GitHub oben rechts auf **+ → New repository** tippen.
2. Namen vergeben, z. B. `eldorado-hunter`.
3. **"Public"** wählen (wichtig, sonst Minuten-Limit!).
4. Haken bei **"Add a README file"** rausnehmen.
5. **Create repository** tippen.
6. Auf der nächsten Seite: **"uploading an existing file"** antippen.
7. Alle Dateien aus dem Zip hochladen (den `.github`-Ordner mit).
8. Ganz unten **Commit changes** tippen.

### 3. Discord-Webhook einrichten
1. In Discord den Server öffnen, in dem die Alerts landen sollen.
2. Rechts oben aufs **Zahnrad** eines Textkanals → **Integrations → Webhooks → New Webhook**.
3. Namen vergeben (z. B. "Eldorado"), **Copy Webhook URL**.

### 4. Webhook als Secret ins Repo eintragen
1. Im Repo auf **Settings → Secrets and variables → Actions**.
2. **New repository secret** antippen.
3. Name: `DISCORD_WEBHOOK`
4. Secret: die kopierte Webhook-URL
5. **Add secret**.

### 5. Action erlauben
1. Im Repo auf **Actions** tippen.
2. **"I understand my workflows, go ahead and enable them"**.
3. Links auf **"Eldorado Hunter"**.
4. Rechts auf **Run workflow → Run workflow** — jetzt startet der erste Testlauf.

Nach ca. 2 Min sollte eine erste Nachricht in deinem Discord-Kanal
auftauchen (entweder Deals oder — falls Eldorados HTML sich geändert
hat — eine Fehlermeldung mit Grund).

## Status prüfen

- **Actions-Tab** im Repo: Zeigt jeden Lauf (grün/rot).
- **state.json** im Repo: `last_run`, `last_error`, `deals_count`,
  `alerts_count`, `new_alerts_sent`.
- **Discord-Kanal**: Deine Alerts.

## Konfig anpassen

In `.github/workflows/scrape.yml`:

```yaml
- cron: "*/15 * * * *"     # Intervall
  ALERT_MULTIPLIER: "2.0"  # ab welchem x-Fachen des Medians Alert
```

In `scraper.py`:

```python
PRICE_MIN_EUR = 0.02
PRICE_MAX_EUR = 30.0
```

Nach jeder Änderung einfach committen — der nächste Lauf nutzt die
neuen Werte.

## Wenn gar keine Alerts kommen

Das ist meistens **kein Fehler**, sondern einfach: in dem Preisbereich
ist gerade nichts außergewöhnlich günstig. Check den Actions-Tab —
wenn jeder Lauf grün ist und `state.json` → `deals_count` > 0 zeigt,
läuft es. Die Schwelle (`ALERT_MULTIPLIER`) kannst du von 2.0 auf
z. B. 1.5 senken, dann kommen mehr Alerts.

Wenn Läufe **rot** sind: Fehler steht in `state.json` → `last_error`.
In 9 von 10 Fällen hat Eldorado seine HTML-Klassen geändert; dann
müssen die Selektoren in `scraper.py` (`scrape_eldorado`-Funktion)
angepasst werden.
