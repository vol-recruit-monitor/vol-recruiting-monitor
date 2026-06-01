"""
Vol Recruiting Monitor – Scraper v4
=====================================
Sources (in order):
  1. X/Twitter API v2     — requires X_BEARER_TOKEN secret
  2. Google News RSS      — FREE, no API key, always works
  3. On3 Recruiting       — HTML + __NEXT_DATA__ parsing
  4. 247Sports            — HTML + __NEXT_DATA__ parsing

Rules:
  - NEVER invents players. Every entry must come from a real source.
  - ALWAYS writes data/offers.json even if every source fails.
  - Logs EVERY step clearly so you can debug in GitHub Actions.
  - Merges new data with existing data across runs.
"""

import os, re, json, time, hashlib, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── Logging (prints to GitHub Actions console) ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ── Tennessee Footprint (15 states, within 2 away) ────────────────────────────
FOOTPRINT_STATES = {
    "TN", "KY", "VA", "NC", "GA", "AL", "MS",
    "AR", "MO", "SC", "FL", "OH", "IN", "WV", "LA"
}

STATE_NAMES = {
    "Tennessee": "TN", "Kentucky": "KY", "Virginia": "VA",
    "North Carolina": "NC", "Georgia": "GA", "Alabama": "AL",
    "Mississippi": "MS", "Arkansas": "AR", "Missouri": "MO",
    "South Carolina": "SC", "Florida": "FL", "Ohio": "OH",
    "Indiana": "IN", "West Virginia": "WV", "Louisiana": "LA",
    **{v: v for v in ["TN","KY","VA","NC","GA","AL","MS","AR","MO","SC","FL","OH","IN","WV","LA"]}
}

# ── School Tiers ──────────────────────────────────────────────────────────────
SEC_SCHOOLS = {
    "Tennessee","Alabama","Auburn","Florida","Georgia","Kentucky","LSU",
    "Mississippi State","Missouri","Ole Miss","South Carolina","Vanderbilt",
    "Arkansas","Texas","Texas A&M","Oklahoma"
}
BIG_TEN = {
    "Ohio State","Michigan","Penn State","Oregon","USC","Wisconsin","Iowa",
    "Minnesota","Illinois","Indiana","Purdue","Nebraska","Northwestern",
    "Maryland","Rutgers","Michigan State","UCLA","Washington"
}
ACC = {
    "Clemson","Florida State","Miami","NC State","Duke","Wake Forest",
    "Louisville","Virginia Tech","Virginia","Boston College","Pitt",
    "Syracuse","Georgia Tech","North Carolina","Notre Dame","SMU","Stanford","Cal"
}
BIG_12 = {
    "Oklahoma State","Texas Tech","TCU","Baylor","Kansas","Kansas State",
    "Iowa State","West Virginia","Cincinnati","UCF","Houston","BYU",
    "Colorado","Arizona","Arizona State","Utah"
}
P4_SCHOOLS = SEC_SCHOOLS | BIG_TEN | ACC | BIG_12

G6_SCHOOLS = {
    "Appalachian State","Coastal Carolina","Georgia Southern","Georgia State",
    "James Madison","Marshall","Old Dominion","Southern Miss","Troy",
    "South Alabama","Texas State","UL Lafayette","UL Monroe","Arkansas State",
    "Toledo","Miami OH","Western Michigan","Central Michigan","Eastern Michigan",
    "Northern Illinois","Ball State","Bowling Green","Ohio","Akron","Buffalo",
    "Kent State","Liberty","Western Kentucky","Middle Tennessee","UTEP","FIU",
    "Jacksonville State","Sam Houston","ETSU","UT Martin","Boise State",
    "Fresno State","San Diego State","Air Force","Colorado State","Wyoming",
    "UNLV","Nevada","Utah State","San Jose State","Hawaii","New Mexico",
    "Memphis","Tulane","UTSA","North Texas","UAB","East Carolina","Charlotte",
    "FAU","Temple","Tulsa","Rice","Navy","Army"
}
ALL_SCHOOLS = P4_SCHOOLS | G6_SCHOOLS

# ── Positional Ideals for Gem Score ──────────────────────────────────────────
POSITION_IDEALS = {
    "QB":(75,215),"RB":(71,210),"WR":(73,195),"TE":(77,240),
    "OL":(77,300),"OT":(77,300),"OG":(76,305),"C":(75,295),
    "DL":(75,275),"DT":(74,290),"DE":(76,255),"EDGE":(76,245),
    "LB":(74,225),"ILB":(74,230),"OLB":(74,220),
    "CB":(72,185),"S":(73,200),"DB":(73,195),
    "ATH":(73,195),"K":(72,195),"P":(73,195)
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}

X_BEARER  = os.environ.get("X_BEARER_TOKEN", "")
DATA_PATH = Path("data/offers.json")

# ── Regex Patterns ────────────────────────────────────────────────────────────
HEIGHT_RE = re.compile(r"(\d)'(\d{1,2})\"?")
WEIGHT_RE = re.compile(r"\b(\d{2,3})\s*(?:lbs?|pounds?)\b", re.I)
CLASS_RE  = re.compile(r"\b(202[5-9]|203[0-2])\b")
STARS_RE  = re.compile(r"\b([2-5])\s*[-–]?\s*star\b", re.I)
NAME_RE   = re.compile(r'\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15})(?:\s+([A-Z][a-z]{1,15}))?\b')

# ── Helper Functions ──────────────────────────────────────────────────────────
def make_id(name: str, year: str) -> str:
    return hashlib.md5(f"{name.lower().strip()}{year}".encode()).hexdigest()[:12]

def in_footprint(text: str) -> bool:
    tu = text.upper()
    for abbr in FOOTPRINT_STATES:
        if re.search(r'\b' + abbr + r'\b', tu):
            return True
    tl = text.lower()
    for name in STATE_NAMES:
        if name.lower() in tl:
            return True
    return False

def get_state(text: str) -> str:
    tu = text.upper()
    for abbr in FOOTPRINT_STATES:
        if re.search(r'\b' + abbr + r'\b', tu):
            return abbr
    tl = text.lower()
    for name, abbr in STATE_NAMES.items():
        if name.lower() in tl and abbr in FOOTPRINT_STATES:
            return abbr
    return ""

def get_height(text: str):
    m = HEIGHT_RE.search(text)
    if m:
        ft, inch = int(m.group(1)), int(m.group(2))
        return ft * 12 + inch, f"{ft}'{inch}\""
    return 0, ""

def get_weight(text: str) -> int:
    m = WEIGHT_RE.search(text)
    return int(m.group(1)) if m else 0

def get_year(text: str) -> str:
    m = CLASS_RE.search(text)
    return m.group(1) if m else "2027"

def get_stars(text: str) -> int:
    m = STARS_RE.search(text)
    return int(m.group(1)) if m else 0

def get_position(text: str) -> str:
    POSITIONS = ["EDGE","ILB","OLB","QB","RB","WR","TE","OT","OG","OL",
                 "DT","DE","DL","LB","CB","ATH","DB","S","K","P","LS"]
    tu = text.upper()
    for pos in POSITIONS:
        if re.search(r'\b' + pos + r'\b', tu):
            return pos
    return "ATH"

def get_offers(text: str) -> list:
    found = []
    tl = text.lower()
    for school in ALL_SCHOOLS:
        if school.lower() in tl:
            found.append(school)
    return list(set(found))

def get_name(text: str) -> str:
    # Skip common non-name patterns
    SKIP = {"The","For","With","From","This","That","His","Her","Their",
            "About","After","Before","During","While","When","Where","What"}
    lines = text.strip().split('\n')
    for line in lines[:3]:
        m = NAME_RE.search(line)
        if m:
            first, last = m.group(1), m.group(2)
            if first not in SKIP and last not in SKIP and first != last:
                third = m.group(3)
                if third and third not in SKIP:
                    return f"{first} {last} {third}"
                return f"{first} {last}"
    return ""

def categorize(offers: list) -> str:
    ol = " ".join(offers).lower()
    for s in SEC_SCHOOLS:
        if s.lower() in ol: return "sec"
    for s in P4_SCHOOLS:
        if s.lower() in ol: return "p4"
    return "g6"

def calc_gem(player: dict) -> int:
    pos = player.get("position", "ATH").upper()
    matched = next((k for k in POSITION_IDEALS if k in pos), "ATH")
    ideal_h, ideal_w = POSITION_IDEALS[matched]
    h = player.get("height_inches", 0)
    w = player.get("weight", 0)
    if not h and not w: return 50
    h_score = max(0, 100 - abs(h - ideal_h) * 12) if h else 50
    w_score = max(0, 100 - abs(w - ideal_w) / max(ideal_w, 1) * 100) if w else 50
    return round((h_score + w_score) / 2)

def build_eval(player: dict) -> dict:
    pos      = player.get("position", "ATH").upper()
    h        = player.get("height_inches", 0)
    hd       = player.get("height_display", "")
    w        = player.get("weight", 0)
    offers   = player.get("offers", [])
    cat      = player.get("category", "g6")
    gem      = player.get("gem_score", 50)
    matched  = next((k for k in POSITION_IDEALS if k in pos), "ATH")
    ideal_h, ideal_w = POSITION_IDEALS[matched]

    S, W = [], []

    if h:
        if h >= ideal_h: S.append(f"At/above ideal height for {pos} ({hd})")
        else:            W.append(f"Slightly short for {pos} ({hd}, ideal {ideal_h//12}'{ideal_h%12}\")")
    else:
        W.append("Height not confirmed")

    if w:
        diff = w - ideal_w
        if abs(diff) <= 15: S.append(f"Ideal frame weight ({w} lbs)")
        elif diff >  20:    W.append(f"May need to trim ({w} lbs vs {ideal_w} lb ideal)")
        else:               W.append(f"Needs to add mass ({w} lbs vs {ideal_w} lb ideal)")
    else:
        W.append("Weight not confirmed")

    n = len(offers)
    if cat == "sec":
        S.append(f"SEC-level interest ({n} offer(s)) — UT should act now")
    elif cat == "p4":
        S.append("P4 interest — UT opportunity window open")
        W.append("No SEC offer yet; UT should evaluate quickly")
    else:
        if gem >= 80:
            S.append("P4-caliber measurables with G6-only offers — underrecruited gem")
            W.append("If film confirms measurables, UT should offer immediately")
        else:
            W.append("Currently G6-only offers")

    if n == 0:
        W.append("No confirmed offers tracked yet")

    rec = "Target" if (cat == "g6" and gem >= 80) or cat in ["sec","p4"] else "Monitor"
    return {
        "strengths":      "; ".join(S) if S else "Evaluation pending",
        "weaknesses":     "; ".join(W) if W else "No concerns flagged",
        "recommendation": rec
    }

def build_player(name: str, text: str, source: str, url: str, label: str,
                 state_override: str = "", year_override: str = "") -> dict | None:
    if not name or len(name) < 5 or " " not in name:
        return None
    h_in, h_disp = get_height(text)
    weight   = get_weight(text)
    grad_yr  = year_override or get_year(text)
    offers   = get_offers(text)
    position = get_position(text)
    state    = state_override or get_state(text)
    stars    = get_stars(text)

    player = {
        "id":             make_id(name, grad_yr),
        "name":           name,
        "position":       position,
        "grad_year":      grad_yr,
        "state":          state,
        "stars":          stars,
        "height_inches":  h_in,
        "height_display": h_disp,
        "weight":         weight,
        "offers":         offers,
        "category":       categorize(offers),
        "source":         source,
        "source_url":     url,
        "source_label":   label,
        "scraped_at":     datetime.now(timezone.utc).isoformat(),
        "x_username":     "",
        "x_handle":       "",
        "hudl_url":       f"https://www.hudl.com/search#query={name.replace(' ','%20')}",
        "uc_url":         f"https://www.ultimaterecruiting.com/search?q={name.replace(' ','+')}",
    }
    player["gem_score"]  = calc_gem(player)
    player["evaluation"] = build_eval(player)
    return player

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1 — X / Twitter API v2
# ─────────────────────────────────────────────────────────────────────────────
def scrape_x() -> list:
    if not X_BEARER:
        log.warning("⚠️  X_BEARER_TOKEN not set — skipping X source")
        return []

    log.info("=" * 50)
    log.info("🐦 SOURCE 1: X/Twitter API")
    log.info("=" * 50)

    QUERIES = [
        '"offer" (Tennessee OR Kentucky OR Georgia OR Alabama OR Florida) football -is:retweet lang:en',
        '"offer" ("North Carolina" OR Virginia OR Mississippi OR Arkansas OR Missouri) football -is:retweet lang:en',
        '"offer" ("South Carolina" OR Ohio OR Indiana OR "West Virginia" OR Louisiana) football -is:retweet lang:en',
        '"offered by" (SEC OR "Big Ten" OR ACC OR "Big 12") football 2026 OR 2027 OR 2028 -is:retweet lang:en',
        '"receives offer" football 2026 OR 2027 OR 2028 -is:retweet lang:en',
        'from:Hayesfawcett3 OR from:ChadSimmons_ OR from:adamgorney "offer" football -is:retweet',
        'from:On3Recruits OR from:247Sports "offer" football -is:retweet',
    ]

    players = []
    endpoint = "https://api.twitter.com/2/tweets/search/recent"
    auth = {"Authorization": f"Bearer {X_BEARER}"}

    for i, query in enumerate(QUERIES, 1):
        log.info(f"  🔍 Query {i}/{len(QUERIES)}: {query[:70]}...")
        try:
            resp = requests.get(endpoint, headers=auth, params={
                "query":       query,
                "max_results": 100,
                "tweet.fields":"created_at,author_id,text",
                "expansions":  "author_id",
                "user.fields": "username,name"
            }, timeout=15)

            log.info(f"     📡 HTTP {resp.status_code}")

            if resp.status_code == 429:
                log.warning("     ⏳ Rate limited — waiting 60s...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                log.warning(f"     ❌ Error: {resp.text[:200]}")
                continue

            data   = resp.json()
            tweets = data.get("data", [])
            users  = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            log.info(f"     ✅ {len(tweets)} tweets returned")

            for tw in tweets:
                text = tw.get("text", "")
                if not in_footprint(text):
                    continue
                if not any(kw in text.lower() for kw in ["offer","offered","receives"]):
                    continue

                name = get_name(text)
                if not name:
                    continue

                state = get_state(text)
                if not state:
                    continue

                author_id = tw.get("author_id","")
                uname = users.get(author_id, {}).get("username","")

                p = build_player(
                    name, text, "x",
                    f"https://twitter.com/{uname}/status/{tw.get('id','')}",
                    f"@{uname} on X",
                    state_override=state
                )
                if p:
                    p["x_username"] = uname
                    p["x_handle"]   = f"@{uname}"
                    players.append(p)
                    log.info(f"     👤 Found: {name} | {state} | {p['position']} | Offers: {p['offers']}")

            time.sleep(2)

        except Exception as e:
            log.error(f"     ❌ Query {i} exception: {e}")

    log.info(f"🐦 X complete — {len(players)} players found\n")
    return players

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2 — Google News RSS (free, no API key, always works)
# ─────────────────────────────────────────────────────────────────────────────
def scrape_google_news() -> list:
    log.info("=" * 50)
    log.info("📰 SOURCE 2: Google News RSS (free)")
    log.info("=" * 50)

    QUERIES = [
        ("Tennessee",     "TN"),
        ("Kentucky",      "KY"),
        ("Georgia",       "GA"),
        ("Alabama",       "AL"),
        ("Florida",       "FL"),
        ("North Carolina","NC"),
        ("Virginia",      "VA"),
        ("Ohio",          "OH"),
        ("Mississippi",   "MS"),
        ("Arkansas",      "AR"),
        ("South Carolina","SC"),
        ("Louisiana",     "LA"),
    ]

    players = []

    for state_name, state_abbr in QUERIES:
        query = f"{state_name}+football+recruiting+offer+2027+OR+2026+OR+2028"
        url   = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            log.info(f"  📡 Google News [{state_name}] HTTP {resp.status_code}")

            if resp.status_code != 200:
                continue

            soup  = BeautifulSoup(resp.content, "lxml-xml")
            items = soup.find_all("item")
            log.info(f"     📰 {len(items)} articles found")

            for item in items[:25]:
                t_tag = item.find("title")
                l_tag = item.find("link")
                d_tag = item.find("description")

                title   = t_tag.get_text(strip=True) if t_tag else ""
                link    = l_tag.get_text(strip=True)  if l_tag else ""
                desc    = d_tag.get_text(strip=True)  if d_tag else ""
                full    = f"{title} {desc}"
                full_lc = full.lower()

                if not any(kw in full_lc for kw in ["offer","offered","commit","recruit"]):
                    continue

                name = get_name(title)
                if not name:
                    name = get_name(full)
                if not name or len(name) < 6:
                    continue

                state = get_state(full) or state_abbr
                if state not in FOOTPRINT_STATES:
                    continue

                p = build_player(name, full, "news", link, "Google News",
                                 state_override=state)
                if p:
                    players.append(p)
                    log.info(f"     👤 Found: {name} | {state} | Offers: {p['offers']}")

            time.sleep(1)

        except Exception as e:
            log.error(f"  ❌ Google News [{state_name}] exception: {e}")

    log.info(f"📰 Google News complete — {len(players)} players found\n")
    return players

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3 — On3
# ─────────────────────────────────────────────────────────────────────────────
def scrape_on3() -> list:
    log.info("=" * 50)
    log.info("🏈 SOURCE 3: On3")
    log.info("=" * 50)

    URLS = [
        "https://www.on3.com/news/category/recruiting/",
        "https://www.on3.com/transfer-portal/wire/football/",
        "https://www.on3.com/db/rankings/2027-national-rankings/football/",
    ]

    players = []

    for url in URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            log.info(f"  📡 On3 [{url[-40:]}] HTTP {resp.status_code}")
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Try __NEXT_DATA__ JSON blob first (Next.js apps embed data here)
            nd = soup.find("script", {"id": "__NEXT_DATA__"})
            if nd:
                try:
                    data = json.loads(nd.string or "{}")
                    extracted = _parse_next_data(data, "on3", url, "On3")
                    log.info(f"     ✅ __NEXT_DATA__: {len(extracted)} players")
                    players.extend(extracted)
                    continue
                except Exception as e:
                    log.warning(f"     ⚠️ __NEXT_DATA__ parse failed: {e}")

            # Fallback: article headline scraping
            headlines = soup.find_all(["h1","h2","h3","h4"], limit=60)
            log.info(f"     📄 Fallback: {len(headlines)} headlines")
            for h in headlines:
                text = h.get_text(" ", strip=True)
                if not any(kw in text.lower() for kw in ["offer","commit","recruit"]):
                    continue
                if not in_footprint(text):
                    continue
                name = get_name(text)
                if not name:
                    continue
                p = build_player(name, text, "on3", url, "On3")
                if p and p["state"] in FOOTPRINT_STATES:
                    players.append(p)
                    log.info(f"     👤 On3: {name}")

            time.sleep(2)
        except Exception as e:
            log.error(f"  ❌ On3 [{url[-40:]}] exception: {e}")

    log.info(f"🏈 On3 complete — {len(players)} players found\n")
    return players

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 4 — 247Sports
# ─────────────────────────────────────────────────────────────────────────────
def scrape_247() -> list:
    log.info("=" * 50)
    log.info("📊 SOURCE 4: 247Sports")
    log.info("=" * 50)

    URLS = [
        "https://247sports.com/Season/2027-Football/Recruits/",
        "https://247sports.com/Season/2026-Football/Recruits/",
        "https://247sports.com/Season/2028-Football/Recruits/",
    ]

    players = []

    for url in URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            log.info(f"  📡 247 [{url[-40:]}] HTTP {resp.status_code}")
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Try __NEXT_DATA__
            nd = soup.find("script", {"id": "__NEXT_DATA__"})
            if nd:
                try:
                    data = json.loads(nd.string or "{}")
                    extracted = _parse_next_data(data, "247sports", url, "247Sports")
                    log.info(f"     ✅ __NEXT_DATA__: {len(extracted)} players")
                    players.extend(extracted)
                    continue
                except Exception as e:
                    log.warning(f"     ⚠️ __NEXT_DATA__ parse failed: {e}")

            # Fallback: look for player-list elements by class name patterns
            items = soup.find_all(class_=re.compile(r"(player|prospect|recruit)", re.I))
            log.info(f"     📄 Fallback: {len(items)} elements")
            for item in items[:60]:
                text = item.get_text(" ", strip=True)
                name = get_name(text)
                if not name:
                    continue
                state = get_state(text)
                if state not in FOOTPRINT_STATES:
                    continue
                p = build_player(name, text, "247sports", url, "247Sports",
                                 state_override=state)
                if p:
                    players.append(p)
                    log.info(f"     👤 247: {name} ({state})")

            time.sleep(2)
        except Exception as e:
            log.error(f"  ❌ 247Sports exception: {e}")

    log.info(f"📊 247Sports complete — {len(players)} players found\n")
    return players

# ─────────────────────────────────────────────────────────────────────────────
# __NEXT_DATA__ universal parser
# ─────────────────────────────────────────────────────────────────────────────
def _parse_next_data(obj, source: str, url: str, label: str,
                     found=None, depth=0) -> list:
    if found is None:
        found = []
    if depth > 12 or len(found) >= 80:
        return found

    if isinstance(obj, dict):
        name = (obj.get("name") or obj.get("playerName") or
                obj.get("fullName") or obj.get("athleteName") or "")
        pos   = obj.get("position") or obj.get("pos") or ""
        state = (obj.get("state") or obj.get("homeState") or
                 obj.get("stateAbbr") or "")

        if isinstance(name, str) and len(name) > 5 and " " in name:
            sa = STATE_NAMES.get(str(state).strip(), str(state).strip())
            if sa in FOOTPRINT_STATES:
                text = json.dumps(obj)
                p = build_player(name, text, source, url, label, state_override=sa)
                if p:
                    if pos:
                        p["position"] = str(pos).upper()[:6]
                    if "stars" in obj:
                        try: p["stars"] = int(obj["stars"])
                        except: pass
                    found.append(p)
                    log.info(f"     👤 __NEXT_DATA__: {name} ({sa})")

        for v in obj.values():
            _parse_next_data(v, source, url, label, found, depth + 1)

    elif isinstance(obj, list):
        for item in obj:
            _parse_next_data(item, source, url, label, found, depth + 1)

    return found

# ─────────────────────────────────────────────────────────────────────────────
# MERGE & SAVE
# ─────────────────────────────────────────────────────────────────────────────
def load_existing() -> dict:
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"⚠️  Could not read existing offers.json: {e}")
    return {"players": [], "last_updated": "never",
            "sources": {"x":0,"news":0,"on3":0,"247sports":0}, "total": 0}

def save_data(existing: dict, new_players: list, source_counts: dict):
    by_id = {p["id"]: p for p in existing.get("players", [])}
    added = updated = 0

    for p in new_players:
        pid = p.get("id")
        if not pid:
            continue
        if pid not in by_id:
            by_id[pid] = p
            added += 1
        else:
            # Merge offers (union) and refresh computed fields
            merged = list(set(by_id[pid].get("offers", [])) | set(p.get("offers", [])))
            by_id[pid]["offers"]     = merged
            by_id[pid]["category"]   = categorize(merged)
            by_id[pid]["gem_score"]  = calc_gem(by_id[pid])
            by_id[pid]["evaluation"] = build_eval(by_id[pid])
            by_id[pid]["scraped_at"] = p["scraped_at"]
            # Update source if newer
            if p.get("source_url"):
                by_id[pid]["source_url"]   = p["source_url"]
                by_id[pid]["source_label"] = p["source_label"]
                by_id[pid]["source"]       = p["source"]
            updated += 1

    log.info(f"💾 +{added} new  |  ↺{updated} updated  |  {len(by_id)} total")

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "players":      list(by_id.values()),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "sources":      source_counts,
        "total":        len(by_id)
    }
    with open(DATA_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    log.info(f"✅ Saved → {DATA_PATH}  ({len(by_id)} players)")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║  VOL RECRUITING MONITOR — SCRAPER v4             ║")
    log.info("║  Sources: X → Google News RSS → On3 → 247Sports  ║")
    log.info("╚══════════════════════════════════════════════════╝")

    existing = load_existing()
    log.info(f"📂 Existing players on file: {len(existing.get('players', []))}\n")

    all_players   = []
    source_counts = {"x": 0, "news": 0, "on3": 0, "247sports": 0}

    # ── X/Twitter ────────────────────────────────────────────────────────────
    try:
        xp = scrape_x()
        source_counts["x"] = len(xp)
        all_players.extend(xp)
    except Exception as e:
        log.error(f"❌ X scraper top-level crash: {e}")

    # ── Google News RSS ───────────────────────────────────────────────────────
    try:
        np_ = scrape_google_news()
        source_counts["news"] = len(np_)
        all_players.extend(np_)
    except Exception as e:
        log.error(f"❌ Google News top-level crash: {e}")

    # ── On3 ──────────────────────────────────────────────────────────────────
    try:
        op = scrape_on3()
        source_counts["on3"] = len(op)
        all_players.extend(op)
    except Exception as e:
        log.error(f"❌ On3 top-level crash: {e}")

    # ── 247Sports ─────────────────────────────────────────────────────────────
    try:
        sp = scrape_247()
        source_counts["247sports"] = len(sp)
        all_players.extend(sp)
    except Exception as e:
        log.error(f"❌ 247Sports top-level crash: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("\n╔══════════════════════════════════════════════════╗")
    log.info(f"║  RUN SUMMARY                                     ║")
    log.info(f"║  X:          {source_counts['x']:>4} players                       ║")
    log.info(f"║  Google News:{source_counts['news']:>4} players                       ║")
    log.info(f"║  On3:        {source_counts['on3']:>4} players                       ║")
    log.info(f"║  247Sports:  {source_counts['247sports']:>4} players                       ║")
    log.info(f"║  TOTAL FOUND:{len(all_players):>4} players this run               ║")
    log.info("╚══════════════════════════════════════════════════╝\n")

    save_data(existing, all_players, source_counts)

    log.info("🏈 SCRAPER COMPLETE — data/offers.json written")

if __name__ == "__main__":
    main()
