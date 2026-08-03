#!/usr/bin/env python3
"""
Agent de veille "error fares / mistake fares"
================================================
V1 : agrégateur de flux (RSS + Reddit) — SANS scraping direct des compagnies
     aériennes ou de Google Flights (trop fragile / bloqué par les anti-bots).

Ce que fait le script :
1. Récupère plusieurs flux RSS connus pour publier des bons plans / erreurs de prix
2. Filtre les articles par mots-clés (type d'alerte + villes de départ qui t'intéressent)
3. Dédoublonne par rapport aux runs précédents (fichier seen.json)
4. Écrit un historique JSON (history.json)
5. Génère une page HTML statique (results.html) que tu ouvres dans ton navigateur

Comment l'utiliser :
    pip install feedparser
    python agent.py

Pour l'automatiser (le faire tourner tout seul régulièrement), voir le README.md
"""

import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import feedparser

# ---------------------------------------------------------------------------
# CONFIGURATION — à adapter à tes besoins
# ---------------------------------------------------------------------------

# Flux RSS surveillés. Tu peux en ajouter / retirer librement.
FEEDS = [
    {"name": "Fly4free", "url": "https://www.fly4free.com/feed/"},
    {"name": "Reddit r/faredrop", "url": "https://www.reddit.com/r/faredrop/.rss"},
    {"name": "Reddit r/awardtravel", "url": "https://www.reddit.com/r/awardtravel/.rss"},
]

# Mots-clés qui indiquent une vraie anomalie de prix (au moins un requis)
ANOMALY_KEYWORDS = ["flight", "vol", "a"]

# Villes / aéroports de départ qui t'intéressent (au moins un requis si la liste
# n'est pas vide ; laisse la liste vide pour ne filtrer que sur ANOMALY_KEYWORDS)
DEPARTURE_KEYWORDS = []

# Un article ne remonte que si (mot-clé anomalie) ET (mot-clé départ), sauf si
# DEPARTURE_KEYWORDS est vide.
REQUIRE_BOTH = True

DATA_DIR = Path(__file__).parent
SEEN_FILE = DATA_DIR / "seen.json"
HISTORY_FILE = DATA_DIR / "history.json"
OUTPUT_HTML = DATA_DIR / "index.html"

# ---------------------------------------------------------------------------
# LOGIQUE
# ---------------------------------------------------------------------------


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def entry_id(entry):
    """Identifiant stable pour dédoublonner (lien si dispo, sinon hash titre+source)."""
    link = entry.get("link")
    if link:
        return hashlib.sha1(link.encode("utf-8")).hexdigest()
    raw = (entry.get("title", "") + entry.get("summary", "")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def matches_filters(title, summary):
    text = f"{title} {summary}".lower()
    has_anomaly = any(kw in text for kw in ANOMALY_KEYWORDS)
    has_departure = (not DEPARTURE_KEYWORDS) or any(kw in text for kw in DEPARTURE_KEYWORDS)

    if REQUIRE_BOTH and DEPARTURE_KEYWORDS:
        return has_anomaly and has_departure
    return has_anomaly or (DEPARTURE_KEYWORDS and has_departure and has_anomaly)


def clean_summary(raw_html, max_len=280):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def fetch_all():
    seen = load_json(SEEN_FILE, {})
    history = load_json(HISTORY_FILE, [])
    new_items = []
    errors = []

    for feed in FEEDS:
        parsed = feedparser.parse(feed["url"])
        if parsed.bozo and not parsed.entries:
            errors.append(f"{feed['name']}: impossible de lire le flux ({parsed.bozo_exception})")
            continue

        for entry in parsed.entries:
            title = entry.get("title", "(sans titre)")
            summary_raw = entry.get("summary", entry.get("description", ""))
            summary = clean_summary(summary_raw)

            if not matches_filters(title, summary_raw):
                continue

            uid = entry_id(entry)
            if uid in seen:
                continue

            item = {
                "id": uid,
                "source": feed["name"],
                "title": title,
                "summary": summary,
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            new_items.append(item)
            seen[uid] = item["detected_at"]

    history = new_items + history
    history = history[:300]  # on garde les 300 dernières alertes

    save_json(SEEN_FILE, seen)
    save_json(HISTORY_FILE, history)

    return history, new_items, errors


# ---------------------------------------------------------------------------
# GÉNÉRATION DE LA PAGE HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Radar // Error Fares</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');

  :root{
    --bg:#0b1220;
    --panel:#101a2e;
    --panel-edge:#1c2b47;
    --text:#e8ecf1;
    --muted:#7c8aa3;
    --amber:#f5a623;
    --alert:#ff5a36;
    --mono: 'IBM Plex Mono', ui-monospace, monospace;
    --sans: 'Inter', system-ui, sans-serif;
  }
  *{box-sizing:border-box;}
  body{
    margin:0;
    background:
      radial-gradient(ellipse at top, #101c33 0%, var(--bg) 60%);
    color:var(--text);
    font-family:var(--sans);
    min-height:100vh;
    padding:32px 20px 80px;
  }
  .wrap{max-width:960px;margin:0 auto;}

  header{
    display:flex;
    justify-content:space-between;
    align-items:flex-end;
    flex-wrap:wrap;
    gap:16px;
    border-bottom:1px solid var(--panel-edge);
    padding-bottom:20px;
    margin-bottom:28px;
  }
  .brand-eyebrow{
    font-family:var(--mono);
    letter-spacing:.18em;
    font-size:11px;
    color:var(--amber);
    text-transform:uppercase;
    margin:0 0 6px;
  }
  h1{
    margin:0;
    font-family:var(--mono);
    font-weight:700;
    font-size:clamp(24px,4vw,34px);
    letter-spacing:-0.01em;
  }
  .meta{
    font-family:var(--mono);
    font-size:12px;
    color:var(--muted);
    text-align:right;
  }
  .meta strong{color:var(--text);}

  .stat-row{
    display:flex;
    gap:12px;
    flex-wrap:wrap;
    margin-bottom:28px;
  }
  .stat{
    font-family:var(--mono);
    background:var(--panel);
    border:1px solid var(--panel-edge);
    border-radius:6px;
    padding:10px 16px;
    font-size:12px;
    color:var(--muted);
  }
  .stat b{
    display:block;
    color:var(--text);
    font-size:20px;
    font-weight:700;
  }

  .board{
    border:1px solid var(--panel-edge);
    border-radius:10px;
    overflow:hidden;
    background:var(--panel);
  }
  .board-head{
    display:grid;
    grid-template-columns: 130px 1fr 150px;
    gap:12px;
    padding:12px 20px;
    font-family:var(--mono);
    font-size:11px;
    letter-spacing:.1em;
    text-transform:uppercase;
    color:var(--muted);
    border-bottom:1px solid var(--panel-edge);
  }
  .row{
    display:grid;
    grid-template-columns: 130px 1fr 150px;
    gap:12px;
    padding:16px 20px;
    border-bottom:1px solid var(--panel-edge);
    align-items:start;
    animation: flap .5s ease;
  }
  .row:last-child{border-bottom:none;}
  .row:hover{background:#141f38;}

  @keyframes flap{
    from{opacity:0; transform: translateY(-4px);}
    to{opacity:1; transform:none;}
  }

  .src{
    font-family:var(--mono);
    font-size:11px;
    color:var(--amber);
    text-transform:uppercase;
    letter-spacing:.05em;
  }
  .title a{
    color:var(--text);
    text-decoration:none;
    font-weight:600;
    font-size:15px;
    line-height:1.4;
  }
  .title a:hover{color:var(--amber); text-decoration:underline;}
  .summary{
    margin-top:6px;
    color:var(--muted);
    font-size:13px;
    line-height:1.5;
  }
  .when{
    font-family:var(--mono);
    font-size:11px;
    color:var(--muted);
    text-align:right;
    white-space:nowrap;
  }

  .empty{
    padding:60px 20px;
    text-align:center;
    color:var(--muted);
    font-family:var(--mono);
    font-size:13px;
  }

  footer{
    margin-top:28px;
    font-family:var(--mono);
    font-size:11px;
    color:var(--muted);
    text-align:center;
  }

  @media (max-width:640px){
    .board-head{display:none;}
    .row{grid-template-columns:1fr; gap:6px;}
    .when{text-align:left;}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <p class="brand-eyebrow">Veille tarifaire &middot; V1</p>
      <h1>RADAR // ERROR FARES</h1>
    </div>
    <div class="meta">Dernière actualisation<br><strong>__GENERATED_AT__</strong></div>
  </header>

  <div class="stat-row">
    <div class="stat"><b>__TOTAL__</b>alertes en mémoire</div>
    <div class="stat"><b>__NEW__</b>nouvelles ce run</div>
    <div class="stat"><b>__SOURCES__</b>sources surveillées</div>
  </div>

  <div class="board">
    <div class="board-head">
      <span>Source</span>
      <span>Alerte</span>
      <span>Détectée</span>
    </div>
    __ROWS__
  </div>

  <footer>Généré par agent.py &middot; relance le script pour rafraîchir cette page</footer>
</div>
</body>
</html>
"""

ROW_TEMPLATE = """<div class="row">
  <div class="src">{source}</div>
  <div>
    <div class="title"><a href="{link}" target="_blank" rel="noopener">{title}</a></div>
    <div class="summary">{summary}</div>
  </div>
  <div class="when">{when}</div>
</div>"""

EMPTY_TEMPLATE = """<div class="empty">Aucune alerte pour l'instant.<br>
Le script tourne, mais rien ne correspond encore à tes filtres — relance-le plus tard,
ou élargis ANOMALY_KEYWORDS / DEPARTURE_KEYWORDS dans agent.py.</div>"""


def format_when(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m %H:%M UTC")
    except (ValueError, TypeError):
        return "—"


def render_html(history, new_count):
    if history:
        rows = "\n".join(
            ROW_TEMPLATE.format(
                source=item["source"],
                link=item["link"] or "#",
                title=item["title"],
                summary=item["summary"],
                when=format_when(item["detected_at"]),
            )
            for item in history
        )
    else:
        rows = EMPTY_TEMPLATE

    html = HTML_TEMPLATE
    html = html.replace("__ROWS__", rows)
    html = html.replace("__TOTAL__", str(len(history)))
    html = html.replace("__NEW__", str(new_count))
    html = html.replace("__SOURCES__", str(len(FEEDS)))
    html = html.replace(
        "__GENERATED_AT__",
        datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
    )
    OUTPUT_HTML.write_text(html, encoding="utf-8")


def main():
    history, new_items, errors = fetch_all()
    render_html(history, len(new_items))

    print(f"[OK] {len(new_items)} nouvelle(s) alerte(s), {len(history)} au total.")
    print(f"[OK] Page générée : {OUTPUT_HTML}")
    if errors:
        print("\n[!] Erreurs sur certains flux :")
        for e in errors:
            print("   -", e)


if __name__ == "__main__":
    main()
