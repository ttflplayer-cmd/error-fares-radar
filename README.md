# Radar // Error Fares — V1

Agent de veille "error fares / mistake fares" qui agrège des flux RSS
(Fly4free, Secret Flying, Reddit...), filtre par mots-clés, et génère une
page HTML que tu consultes quand tu veux. Pas de Telegram, pas de scraping
direct des compagnies aériennes ou de Google Flights.

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

```bash
python agent.py
```

Puis ouvre `results.html` dans ton navigateur (double-clic suffit, pas besoin
de serveur local).

À chaque exécution, le script :
- récupère les flux RSS configurés
- garde seulement les articles qui matchent tes mots-clés (`ANOMALY_KEYWORDS`
  + `DEPARTURE_KEYWORDS`)
- ignore ce qu'il a déjà vu lors d'un run précédent (`seen.json`)
- ajoute les nouveautés à l'historique (`history.json`, 300 dernières alertes)
- régénère `results.html` avec tout l'historique dedans

## Personnaliser les filtres

Ouvre `agent.py`, tout se configure en haut du fichier :

- `FEEDS` : liste des flux RSS surveillés. Ajoute-en autant que tu veux.
- `ANOMALY_KEYWORDS` : mots qui indiquent une vraie anomalie de prix.
- `DEPARTURE_KEYWORDS` : villes/aéroports de départ qui t'intéressent. Laisse
  la liste vide (`[]`) si tu veux voir toutes les anomalies, peu importe la
  ville de départ.

### ⚠️ À vérifier / adapter

- Le flux **Fly4free** (`fly4free.com/feed`) est confirmé actif.
- Le flux **Secret Flying** a peut-être changé de politique (le site pousse
  maintenant vers une inscription par e-mail plutôt qu'un flux RSS public
  ouvert) — si le script te signale une erreur dessus au premier run,
  supprime-le simplement de `FEEDS`, ou remplace-le par l'URL RSS correcte
  si tu en trouves une valide.
- Les flux **Reddit** (`reddit.com/r/xxx/.rss`) fonctionnent tant que le
  subreddit existe et reste public. Tu peux ajouter d'autres subreddits
  pertinents (ex. `r/awardtravel`, `r/churning`) sur le même modèle d'URL.

Le script ne plante jamais si un flux est cassé : il logue l'erreur dans le
terminal et continue avec les autres flux.

## Automatiser avec GitHub Actions + GitHub Pages (recommandé)

Avec cette config, le script tourne automatiquement toutes les 30 minutes
dans le cloud (gratuit) et la page est accessible à une URL fixe depuis ton
téléphone ou n'importe quel appareil — rien à faire tourner chez toi.

Le fichier `.github/workflows/update.yml` est déjà prêt dans ce dossier.
Il fait 3 choses à chaque exécution : installe les dépendances, lance
`agent.py`, puis commit + push `index.html`, `history.json` et `seen.json`
s'il y a du nouveau.

### Étape 1 — Créer le dépôt GitHub
1. Va sur [github.com/new](https://github.com/new)
2. Nom du repo : ce que tu veux (ex. `error-fares-radar`)
3. **Visibilité : Public** (important — les minutes GitHub Actions sont
   illimitées et gratuites sur un repo public ; sur un repo privé tu es
   limité à 2000 minutes/mois, ce qui suffirait quand même largement, mais
   autant éviter la limite)
4. Ne coche aucune case d'initialisation (pas de README auto), on va tout
   pousser nous-mêmes

### Étape 2 — Pousser ce dossier
Depuis ce dossier (`error-fares-agent/`), en local :
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/TON-PSEUDO/TON-REPO.git
git push -u origin main
```

### Étape 3 — Activer GitHub Pages
1. Dans le repo sur GitHub : **Settings → Pages**
2. Sous "Build and deployment" → Source : **Deploy from a branch**
3. Branch : **main**, dossier : **/ (root)**
4. Enregistre. GitHub te donne une URL du type :
   `https://ton-pseudo.github.io/ton-repo/`
5. Cette URL affichera directement `index.html` — c'est ta page à
   consulter depuis ton téléphone, à mettre en favori ou en raccourci
   d'écran d'accueil

### Étape 4 — Vérifier que le workflow tourne
1. Onglet **Actions** du repo → tu dois voir "Mise à jour du radar error
   fares"
2. Pour ne pas attendre 30 minutes la première fois, clique dessus puis
   **Run workflow** (bouton en haut à droite) pour le lancer manuellement
3. Une fois le run vert ✅, `index.html` a été commité automatiquement —
   recharge ta page GitHub Pages, les données doivent apparaître (avec un
   léger délai, GitHub Pages met parfois 1-2 min à republier après un push)

### ⚠️ Deux limites à connaître
- **GitHub désactive les workflows programmés (`schedule`) après 60 jours
  sans aucune activité de push sur le repo.** Comme ce workflow commit
  lui-même dès qu'il y a du nouveau, ça ne devrait pas arriver en usage
  normal ; mais si tu vois que le radar ne se met plus à jour après une
  longue pause, va dans Actions et relance-le manuellement (**Run
  workflow**) pour le réactiver.
- L'intervalle `cron` de GitHub Actions est une fréquence *minimale*, pas
  garantie à la minute près — en période de forte charge sur
  l'infrastructure GitHub, l'exécution peut être décalée de quelques
  minutes. Sans impact réel pour ce cas d'usage.

## Alternative — le faire tourner en local (sans cloud)

Si tu préfères ne pas dépendre de GitHub Actions :

### macOS / Linux — cron
```bash
crontab -e
# ajoute cette ligne pour lancer toutes les 30 minutes :
*/30 * * * * cd /chemin/vers/error-fares-agent && /usr/bin/python3 agent.py >> agent.log 2>&1
```

### Windows — Planificateur de tâches
Crée une tâche qui exécute :
```
python C:\chemin\vers\error-fares-agent\agent.py
```
avec un déclencheur "toutes les 30 minutes". Dans ce cas, ouvre
`index.html` directement en local (double-clic) — pas d'URL distante.

## Prochaines étapes possibles (V2 / V3)

- **Base de prix historique** : brancher une vraie API de vols (Amadeus
  Self-Service, tier gratuit) pour surveiller des routes précises au départ
  de tes aéroports et détecter les écarts par rapport à un prix médian
  calculé sur plusieurs semaines — c'est ce qui manque le plus à cette V1
  pour détecter des anomalies que personne n'a encore repérées ailleurs.
- **Hébergement + alerte "extrême uniquement"** : déployer sur GitHub Pages
  et n'ajouter une notif (mail/Telegram) que pour les cas vraiment rares
  (ex. -70% ou plus), pour ne pas être noyé de notifications.
