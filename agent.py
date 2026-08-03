#!/usr/bin/env python3
"""
Agent de veille "error fares / mistake fares"
================================================
V2 : agrégateur de flux (RSS + Reddit) + page HTML interactive avec filtres
     cliquables (type d'offre, ville de départ, destination).

Ce que fait le script :
1. Récupère plusieurs flux RSS connus pour publier des bons plans / erreurs de prix
2. Filtre les articles par mots-clés (type d'alerte + villes de départ qui t'intéressent)
3. Dédoublonne par rapport aux runs précédents (fichier seen.json)
4. Écrit un historique JSON (history.json)
5. Pour chaque alerte, essaie d'extraire : catégorie (Vol / Hôtel / Séjour),
   ville de départ, destination, prix — à partir du titre de l'article.
   C'est une extraction "au mieux" (heuristique par mots-clés / regex), pas
   une lecture structurée d'une vraie base de données : certains titres mal
   formés ou atypiques ne donneront pas d'infos complètes (affiché "—").
6. Génère une page HTML statique (index.html) avec des filtres cliquables :
   catégorie, ville de départ, destination — 100% en JavaScript côté
   navigateur, aucun serveur requis.

Comment l'utiliser :
    pip install feedparser
    python agent.py

Pour l'automatiser (le faire tourner tout seul régulièrement), voir le README.md
"""

import json
import re
import hashlib
import socket
from datetime import datetime, timezone
from pathlib import Path

import feedparser

# Empêche le script de rester bloqué indéfiniment si un flux ne répond pas :
# limite tous les appels réseau (y compris ceux de feedparser) à 10 secondes.
socket.setdefaulttimeout(10)

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
DEPARTURE_KEYWORDS = ["paris", "cdg", "orly", "france"]

# Un article ne remonte que si (mot-clé anomalie) ET (mot-clé départ), sauf si
# DEPARTURE_KEYWORDS est vide.
REQUIRE_BOTH = True

DATA_DIR = Path(__file__).parent
SEEN_FILE = DATA_DIR / "seen.json"
HISTORY_FILE = DATA_DIR / "history.json"
OUTPUT_HTML = DATA_DIR / "index.html"

# ---------------------------------------------------------------------------
# LOGIQUE DE COLLECTE
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
# EXTRACTION "AU MIEUX" : catégorie / départ / destination / prix
# ---------------------------------------------------------------------------
# Ces titres viennent de flux RSS écrits par des humains, dans des formats
# variés — cette extraction est une heuristique, pas un parsing garanti.
# Ce qui n'est pas détecté s'affiche "—" dans l'interface plutôt qu'une
# fausse info.

FLIGHT_WORDS = ("flight", "flights", "vol ", "vols ", "non-stop", "nonstop", "fly ")
HOTEL_WORDS = ("hotel", "hôtel", "resort", " stay", "b&b", "bnb", "double", "suite")
PACKAGE_WORDS = ("holiday", "package", "p.p", "all-inclusive", "all inclusive")

ROUTE_RE = re.compile(r"\bfrom\s+(.+?)\s+to\s+(.+)$", re.IGNORECASE)
DEST_IN_RE = re.compile(r"\bin\s+([A-ZÀ-Ý][\w\s,'\-]{2,30})", re.IGNORECASE)
ORIGIN_FROM_RE = re.compile(r"\bflights?\s+from\s+([A-ZÀ-Ý][\w\s,&'\-]{2,30})", re.IGNORECASE)
PRICE_RE = re.compile(r"([€£$])\s?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)")
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FFFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]"
)


def categorize(title):
    t = title.lower()
    has_flight = any(w in t for w in FLIGHT_WORDS)
    has_hotel = any(w in t for w in HOTEL_WORDS)
    has_package = any(w in t for w in PACKAGE_WORDS) or (has_flight and has_hotel)
    if has_package:
        return "Séjour"
    if has_flight:
        return "Vol"
    if has_hotel:
        return "Hôtel"
    return "Autre"


def clean_location(raw):
    if not raw:
        return None
    s = re.split(r"\bfor\b|\bfrom\b|[–—]", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    s = EMOJI_RE.sub("", s)
    s = re.sub(r"[^\w\s&,.'\-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip(" ,.-")
    return s or None


def extract_details(title):
    category = categorize(title)
    origin = destination = None

    m = ROUTE_RE.search(title)
    if m:
        origin = clean_location(m.group(1))
        destination = clean_location(m.group(2))
    elif category in ("Hôtel", "Séjour"):
        m2 = DEST_IN_RE.search(title)
        if m2:
            destination = clean_location(m2.group(1))
        m3 = ORIGIN_FROM_RE.search(title)
        if m3:
            origin = clean_location(m3.group(1))

    mp = PRICE_RE.search(title)
    price = f"{mp.group(1)}{mp.group(2)}" if mp else None

    return {
        "category": category,
        "origin": origin or "—",
        "destination": destination or "—",
        "price": price or "—",
    }


def format_when(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m %H:%M UTC")
    except (ValueError, TypeError):
        return "—"


def enrich(history):
    """Ajoute catégorie / départ / destination / prix / date lisible à chaque alerte."""
    enriched = []
    for item in history:
        details = extract_details(item["title"])
        enriched.append({
            **item,
            **details,
            "when": format_when(item["detected_at"]),
        })
    return enriched


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
    background: radial-gradient(ellipse at top, #101c33 0%, var(--bg) 60%);
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
    margin-bottom:24px;
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
    margin-bottom:20px;
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

  /* --- Barre de filtres --- */
  .filters{
    display:flex;
    gap:10px;
    flex-wrap:wrap;
    align-items:center;
    margin-bottom:20px;
    padding:14px 16px;
    background:var(--panel);
    border:1px solid var(--panel-edge);
    border-radius:10px;
  }
  .chip-group{display:flex; gap:6px; flex-wrap:wrap;}
  .chip{
    font-family:var(--mono);
    font-size:11px;
    text-transform:uppercase;
    letter-spacing:.05em;
    padding:7px 13px;
    border-radius:20px;
    border:1px solid var(--panel-edge);
    background:var(--bg);
    color:var(--muted);
    cursor:pointer;
    transition:.15s;
  }
  .chip:hover{border-color:var(--amber); color:var(--text);}
  .chip.active{background:var(--amber); color:#1a1206; border-color:var(--amber); font-weight:600;}

  select{
    font-family:var(--mono);
    font-size:12px;
    background:var(--bg);
    color:var(--text);
    border:1px solid var(--panel-edge);
    border-radius:6px;
    padding:8px 10px;
    cursor:pointer;
  }
  select:focus{outline:2px solid var(--amber); outline-offset:1px;}

  .reset-btn{
    font-family:var(--mono);
    font-size:11px;
    color:var(--muted);
    background:none;
    border:1px solid transparent;
    text-decoration:underline;
    cursor:pointer;
    padding:6px 4px;
    margin-left:auto;
  }
  .reset-btn:hover{color:var(--alert);}

  .shown-count{
    font-family:var(--mono);
    font-size:12px;
    color:var(--muted);
    margin-bottom:12px;
  }
  .shown-count b{color:var(--text);}

  .board{
    border:1px solid var(--panel-edge);
    border-radius:10px;
    overflow:hidden;
    background:var(--panel);
  }

  .card{
    padding:16px 20px;
    border-bottom:1px solid var(--panel-edge);
    animation: flap .4s ease;
  }
  .card:last-child{border-bottom:none;}
  .card:hover{background:#141f38;}

  @keyframes flap{
    from{opacity:0; transform: translateY(-4px);}
    to{opacity:1; transform:none;}
  }

  .card-top{
    display:flex;
    align-items:center;
    gap:10px;
    flex-wrap:wrap;
    margin-bottom:8px;
  }
  .badge{
    font-family:var(--mono);
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:.06em;
    padding:3px 9px;
    border-radius:4px;
    border:1px solid var(--panel-edge);
    color:var(--muted);
    white-space:nowrap;
  }
  .badge.vol{background:rgba(245,166,35,.15); color:var(--amber); border-color:rgba(245,166,35,.4);}
  .badge.hotel{background:rgba(124,138,163,.15); color:var(--muted); border-color:var(--panel-edge);}
  .badge.sejour{background:rgba(255,90,54,.12); color:var(--alert); border-color:rgba(255,90,54,.3);}

  .route{
    font-family:var(--mono);
    font-size:13px;
    font-weight:600;
    color:var(--text);
  }
  .price{
    font-family:var(--mono);
    font-weight:700;
    color:var(--amber);
    font-size:15px;
    margin-left:auto;
  }

  .card-title a{
    color:var(--text);
    text-decoration:none;
    font-weight:600;
    font-size:15px;
    line-height:1.4;
  }
  .card-title a:hover{color:var(--amber); text-decoration:underline;}
  .card-summary{
    margin-top:6px;
    color:var(--muted);
    font-size:13px;
    line-height:1.5;
  }
  .card-footer{
    display:flex;
    justify-content:space-between;
    gap:10px;
    margin-top:10px;
    font-family:var(--mono);
    font-size:11px;
    color:var(--muted);
  }
  .card-footer .src{color:var(--amber); text-transform:uppercase; letter-spacing:.05em;}

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
    .filters{flex-direction:column; align-items:stretch;}
    .reset-btn{margin-left:0; text-align:right;}
    .price{margin-left:0;}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <p class="brand-eyebrow">Veille tarifaire &middot; V2</p>
      <h1>RADAR // ERROR FARES</h1>
    </div>
    <div class="meta">Dernière actualisation<br><strong>__GENERATED_AT__</strong></div>
  </header>

  <div class="stat-row">
    <div class="stat"><b>__TOTAL__</b>alertes en mémoire</div>
    <div class="stat"><b>__NEW__</b>nouvelles ce run</div>
    <div class="stat"><b>__SOURCES__</b>sources surveillées</div>
  </div>

  <div class="filters">
    <div class="chip-group" id="category-filters"></div>
    <select id="origin-filter"></select>
    <select id="destination-filter"></select>
    <button class="reset-btn" id="reset-btn">Réinitialiser les filtres</button>
  </div>

  <p class="shown-count" id="shown-count"></p>

  <div class="board" id="board"></div>

  <footer>Généré par agent.py &middot; relance le script pour rafraîchir cette page</footer>
</div>

<script id="deals-data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById('deals-data').textContent);
  const board = document.getElementById('board');
  const shownCount = document.getElementById('shown-count');
  const categoryWrap = document.getElementById('category-filters');
  const originSelect = document.getElementById('origin-filter');
  const destinationSelect = document.getElementById('destination-filter');
  const resetBtn = document.getElementById('reset-btn');

  const state = { category: 'Tous', origin: 'Tous', destination: 'Tous' };

  const categories = ['Tous', 'Vol', 'Hôtel', 'Séjour', 'Autre'];
  const badgeClass = { 'Vol': 'vol', 'Hôtel': 'hotel', 'Séjour': 'sejour', 'Autre': '' };

  function uniqueSorted(values) {
    return Array.from(new Set(values.filter(v => v && v !== '—'))).sort((a, b) =>
      a.localeCompare(b, 'fr'));
  }

  function buildSelect(select, values, allLabel) {
    select.innerHTML = '';
    const optAll = document.createElement('option');
    optAll.value = 'Tous';
    optAll.textContent = allLabel;
    select.appendChild(optAll);
    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      select.appendChild(opt);
    });
  }

  function buildChips() {
    categoryWrap.innerHTML = '';
    categories.forEach(cat => {
      const chip = document.createElement('button');
      chip.className = 'chip' + (cat === state.category ? ' active' : '');
      chip.textContent = cat === 'Tous' ? 'Tous' : cat + 's';
      chip.dataset.category = cat;
      chip.addEventListener('click', () => {
        state.category = cat;
        render();
      });
      categoryWrap.appendChild(chip);
    });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  function render() {
    // met à jour l'état visuel des chips
    Array.from(categoryWrap.children).forEach(chip => {
      chip.classList.toggle('active', chip.dataset.category === state.category);
    });

    const filtered = DATA.filter(item => {
      if (state.category !== 'Tous' && item.category !== state.category) return false;
      if (state.origin !== 'Tous' && item.origin !== state.origin) return false;
      if (state.destination !== 'Tous' && item.destination !== state.destination) return false;
      return true;
    });

    shownCount.innerHTML = '<b>' + filtered.length + '</b> alerte(s) affichée(s) sur ' + DATA.length;

    if (filtered.length === 0) {
      board.innerHTML = '<div class="empty">Aucune alerte ne correspond à ces filtres.<br>' +
        'Essaie "Réinitialiser les filtres" pour tout revoir.</div>';
      return;
    }

    board.innerHTML = filtered.map(item => {
      const cls = badgeClass[item.category] || '';
      const route = (item.origin !== '—' || item.destination !== '—')
        ? '<span class="route">' + escapeHtml(item.origin) + ' → ' + escapeHtml(item.destination) + '</span>'
        : '';
      const price = item.price !== '—'
        ? '<span class="price">' + escapeHtml(item.price) + '</span>'
        : '';
      return (
        '<div class="card">' +
          '<div class="card-top">' +
            '<span class="badge ' + cls + '">' + escapeHtml(item.category) + '</span>' +
            route +
            price +
          '</div>' +
          '<div class="card-title"><a href="' + escapeHtml(item.link || '#') + '" target="_blank" rel="noopener">' +
            escapeHtml(item.title) + '</a></div>' +
          '<div class="card-summary">' + escapeHtml(item.summary) + '</div>' +
          '<div class="card-footer">' +
            '<span class="src">' + escapeHtml(item.source) + '</span>' +
            '<span>' + escapeHtml(item.when) + '</span>' +
          '</div>' +
        '</div>'
      );
    }).join('');
  }

  buildChips();
  buildSelect(originSelect, uniqueSorted(DATA.map(d => d.origin)), 'Tous les départs');
  buildSelect(destinationSelect, uniqueSorted(DATA.map(d => d.destination)), 'Toutes les destinations');

  originSelect.addEventListener('change', () => { state.origin = originSelect.value; render(); });
  destinationSelect.addEventListener('change', () => { state.destination = destinationSelect.value; render(); });
  resetBtn.addEventListener('click', () => {
    state.category = 'Tous'; state.origin = 'Tous'; state.destination = 'Tous';
    originSelect.value = 'Tous'; destinationSelect.value = 'Tous';
    render();
  });

  render();
})();
</script>
</body>
</html>
"""


def render_html(history, new_count):
    enriched = enrich(history)

    html = HTML_TEMPLATE
    html = html.replace("__DATA_JSON__", json.dumps(enriched, ensure_ascii=False))
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
