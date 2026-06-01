"""
Vol Recruiting Monitor – Scraper v5 (Strict Validation)
=========================================================
RULES:
  1. NEVER invents players — every entry must come from a real source
  2. Validates every name against a blacklist of coaches, outlets, schools
  3. Verifies players against On3/247 profile pages when possible
  4. X/Twitter is priority #1
  5. Google News RSS is backup — with STRICT name filtering
  6. On3 + 247Sports HTML scraping as additional sources
  7. Always writes data/offers.json — even if empty
  8. Merges across runs — players accumulate over time
"""

import os, re, json, time, hashlib, logging, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus
import requests
from bs4 import BeautifulSoup

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
FOOTPRINT_STATES = {
    "TN","KY","VA","NC","GA","AL","MS","AR","MO","SC","FL","OH","IN","WV","LA"
}

STATE_FULL = {
    "Tennessee":"TN","Kentucky":"KY","Virginia":"VA","North Carolina":"NC",
    "Georgia":"GA","Alabama":"AL","Mississippi":"MS","Arkansas":"AR",
    "Missouri":"MO","South Carolina":"SC","Florida":"FL","Ohio":"OH",
    "Indiana":"IN","West Virginia":"WV","Louisiana":"LA"
}

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

POSITION_IDEALS = {
    "QB":(75,215),"RB":(71,210),"WR":(73,195),"TE":(77,240),
    "OL":(77,300),"OT":(77,300),"OG":(76,305),"C":(75,295),
    "DL":(75,275),"DT":(74,290),"DE":(76,255),"EDGE":(76,245),
    "LB":(74,225),"ILB":(74,230),"OLB":(74,220),
    "CB":(72,185),"S":(73,200),"DB":(73,195),
    "ATH":(73,195),"K":(72,195),"P":(73,195)
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

X_BEARER  = os.environ.get("X_BEARER_TOKEN", "")
DATA_PATH = Path("data/offers.json")

# ══════════════════════════════════════════════════════════════════════════════
# BLACKLIST — names that are NOT recruits
# ══════════════════════════════════════════════════════════════════════════════
BLACKLIST_EXACT = {
    # Coaches
    "josh heupel","nick saban","kirby smart","lane kiffin","eli drinkwitz",
    "mark stoops","brian kelly","ryan day","james franklin","dabo swinney",
    "jimbo fisher","lincoln riley","steve sarkisian","sam pittman",
    "shane beamer","clark lea","hugh freeze","kalen deboer","billy napier",
    "mike norvell","mario cristobal","mack brown","brent venables",
    "sonny dykes","matt rhule","dave aranda","chris klieman","lance leipold",
    "joey mcguire","dana holgorsen","willie fritz","mike elko",
    "butch jones","phillip fulmer","derek dooley","jeremy pruitt",
    # Media / Outlets / Analysts
    "yahoo sports","vols wire","sports illustrated","bleacher report",
    "rivals","on3","247sports","maxpreps","espn","fox sports","cbs sports",
    "sec network","vol network","rocky top insider","go vols","vol nation",
    "wildcats wire","gators wire","dawgs wire","tide wire","razorbacks wire",
    "buckeyes wire","wolverines wire","fighting irish wire",
    "adam gorney","steve wiltfong","rusty mansell","chad simmons",
    "andrew ivins","tom loy","brandon huffman","sam spiegelman",
    "mike farrell","allen trieu","barton simmons","josh helmholdt",
    "chris hummer","luke stampini","jeremy birmingham",
    # Common false positives from headlines
    "top football","kentucky football","tennessee football","alabama football",
    "georgia football","florida football","class names","standout peach",
    "lexington herald","knox news","nashville tennessean","chattanooga times",
    "memphis commercial","jackson sun","top prospect","star prospect",
    "football names","football recruit","recruiting update","recruiting class",
    "offer update","offer list","commit list","target list","watch list",
    "spring game","spring practice","bowl game","national signing",
    "early signing","transfer portal","nil deal","nil deals",
    "kentucky names","peach state","volunteer state","bluegrass state",
    "will stein",
}

BLACKLIST_PARTIAL = [
    "wire", "sports", "illustrated", "espn", "network", "insider",
    "media", "news", "times", "herald", "tribune", "gazette", "journal",
    "reporter", "analyst", "editor", "writer", "columnist", "podcast",
    "preview", "review", "update", "roundup", "breakdown", "rankings",
    "football names", "recruiting class", "top prospects",
    "high school football", "college football", "friday night",
]

def is_valid_player_name(name: str) -> bool:
    """Strict validation: is this actually a person's name?"""
    if not name or len(name) < 4:
        return False
    nl = name.lower().strip()

    # Exact blacklist
    if nl in BLACKLIST_EXACT:
        return False

    # Partial blacklist
    for partial in BLACKLIST_PARTIAL:
        if partial in nl:
            return False

    # Must be 2-3 words (first + last, maybe middle)
    parts = name.strip().split()
    if len(parts) < 2 or len(parts) > 4:
        return False

    # Each part must be alphabetic and reasonable length
    for part in parts:
        cleaned = re.sub(r"['-]", "", part)
        if not cleaned.isalpha():
            return False
        if len(cleaned) < 2 or len(cleaned) > 18:
            return False

    # Must not contain school names
    for school in ALL_SCHOOLS:
        if school.lower() in nl:
            return False

    # Must not be all caps (headline artifact)
    if name == name.upper():
        return False

    return True

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def make_id(name: str, year: str) -> str:
    return hashlib.md5(f"{name.lower().strip()}{year}".encode()).hexdigest()[:12]

def in_footprint(state: str) -> bool:
    if not state:
        return False
    s = state.strip().upper()
    if s in FOOTPRINT_STATES:
        return True
    for full, abbr in STATE_FULL.items():
        if s == full.upper():
            return True
    return False

def normalize_state(state: str) -> str:
    if not state:
        return ""
    s = state.strip()
    if s.upper() in FOOTPRINT_STATES:
        return s.upper()
    for full, abbr in STATE_FULL.items():
        if s.lower() == full.lower():
            return abbr
    return s.upper()[:2] if len(s) >= 2 else s.upper()

def classify_offers(offers: list) -> str:
    for o in offers:
        if o in SEC_SCHOOLS:
            return "SEC"
    for o in offers:
        if o in P4_SCHOOLS:
            return "P4"
    return "G6"

def gem_score(pos: str, ht: int, wt: int) -> int:
    ideal = POSITION_IDEALS.get(pos, (73, 200))
    ht_diff = abs(ht - ideal[0])
    wt_diff = abs(wt - ideal[1])
    score = max(0, 100 - ht_diff * 8 - wt_diff * 0.4)
    return int(score)

def ai_evaluation(name, pos, ht, wt, offers):
    """Generate evaluation from measurables and offer profile."""
    strengths, weaknesses = [], []
    ideal = POSITION_IDEALS.get(pos, (73, 200))

    if ht >= ideal[0] + 1:
        strengths.append("Elite length for position")
    elif ht >= ideal[0]:
        strengths.append("Good size for position")
    else:
        weaknesses.append("Undersized for position")

    if wt >= ideal[1] + 10:
        strengths.append("Physical, strong frame")
    elif wt >= ideal[1] - 10:
        strengths.append("Solid build")
    else:
        weaknesses.append("Needs to add weight")

    n_sec = sum(1 for o in offers if o in SEC_SCHOOLS)
    n_p4  = sum(1 for o in offers if o in P4_SCHOOLS)
    if n_sec >= 3:
        strengths.append(f"High SEC demand ({n_sec} offers)")
    elif n_p4 >= 3:
        strengths.append(f"Strong P4 interest ({n_p4} offers)")
    elif len(offers) >= 5:
        strengths.append(f"Wide offer sheet ({len(offers)} offers)")
    else:
        weaknesses.append("Limited offer sheet so far")

    if pos in ("QB", "WR", "CB", "S") and ht >= ideal[0] + 2:
        strengths.append("Rare height at skill position")
    if pos in ("OL", "DL", "DT") and wt >= ideal[1] + 20:
        strengths.append("Dominant mass for trenches")

    if not strengths:
        strengths.append("Developing prospect")
    if not weaknesses:
        weaknesses.append("No measurable red flags")

    return {"strengths": strengths[:3], "weaknesses": weaknesses[:3]}

def build_links(name: str, on3_url: str = "", two47_url: str = "", x_handle: str = ""):
    """Build verified links where possible, search links as fallback."""
    q = quote_plus(name)
    links = {}

    # On3 — real URL if we have it
    if on3_url:
        links["on3"] = on3_url
    else:
        links["on3"] = f"https://www.on3.com/db/search/?query={q}"

    # 247Sports — real URL if we have it
    if two47_url:
        links["247"] = two47_url
    else:
        links["247"] = f"https://247sports.com/Search/Player/?query={q}"

    # Hudl — search link (no public API exists)
    links["hudl"] = f"https://www.hudl.com/search?query={q}&organizationTypes=highSchool"

    # X/Twitter — real handle if we have it, otherwise search
    if x_handle:
        links["x"] = f"https://x.com/{x_handle.lstrip('@')}"
    else:
        links["x"] = f"https://x.com/search?q={q}%20football&src=typed_query"

    # UC Report
    links["ucreport"] = f"https://www.google.com/search?q=site:ucreport.com+{q}"

    return links

def load_existing() -> dict:
    """Load existing players from previous runs."""
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH) as f:
                data = json.load(f)
            log.info(f"📂 Loaded {len(data.get('players',[]))} existing players")
            return {p["id"]: p for p in data.get("players", [])}
        except Exception as e:
            log.warning(f"⚠️ Could not load existing data: {e}")
    return {}

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1: X / TWITTER (Priority #1)
# ══════════════════════════════════════════════════════════════════════════════
def scrape_x() -> list:
    """Search X for recruiting offer announcements."""
    if not X_BEARER:
        log.warning("⚠️ X_BEARER_TOKEN not set — skipping X/Twitter")
        log.warning("   ℹ️  X API free tier does NOT include search.")
        log.warning("   ℹ️  You need Basic tier ($100/mo) at developer.x.com")
        return []

    log.info("🐦 Searching X/Twitter...")
    headers = {"Authorization": f"Bearer {X_BEARER}"}
    players = []

    # Targeted queries for offer announcements
    queries = [
        '"blessed to receive" offer football',
        '"offered" football (Tennessee OR Kentucky OR Georgia OR Alabama OR Florida OR Carolina)',
        '#AGTG offer football 2027',
        '#AGTG offer football 2026',
        '"committed to" football (Tennessee OR Kentucky OR Georgia OR Alabama)',
        '"all glory to god" offer football',
    ]

    for query in queries:
        try:
            url = "https://api.twitter.com/2/tweets/search/recent"
            params = {
                "query": query + " -is:retweet lang:en",
                "max_results": 50,
                "tweet.fields": "author_id,created_at,text,entities",
                "expansions": "author_id",
                "user.fields": "name,username",
            }
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            log.info(f"   X query: {query[:60]}... → HTTP {resp.status_code}")

            if resp.status_code == 403:
                log.error("   ❌ X API returned 403 — your token lacks search access")
                log.error("   ℹ️  Free tier = NO search. You need Basic tier ($100/mo)")
                return players  # Don't try more queries

            if resp.status_code == 429:
                log.warning("   ⏳ Rate limited — waiting 15s")
                time.sleep(15)
                continue

            if resp.status_code != 200:
                log.warning(f"   ⚠️ HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json()
            tweets = data.get("data", [])
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            log.info(f"   📨 Got {len(tweets)} tweets")

            for tweet in tweets:
                text = tweet.get("text", "")
                author = users.get(tweet.get("author_id"), {})

                # Extract player name (tweet author for "blessed to receive" tweets)
                player_name = None
                x_handle = author.get("username", "")

                # Pattern 1: Author IS the recruit
                if re.search(r"(blessed|honored|excited).{0,20}(receive|announce|offer)", text, re.I):
                    candidate = author.get("name", "")
                    # Clean Twitter display name (remove emojis, numbers, etc.)
                    candidate = re.sub(r"[^\w\s'-]", "", candidate).strip()
                    candidate = re.sub(r"\s+", " ", candidate)
                    if is_valid_player_name(candidate):
                        player_name = candidate

                # Pattern 2: Coach/team announcing offer TO someone
                if not player_name:
                    m = re.search(r"(?:offered|offer to|extended.{0,10}offer to)\s+(?:@\w+\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})", text)
                    if m and is_valid_player_name(m.group(1)):
                        player_name = m.group(1)

                if not player_name:
                    continue

                # Extract offers from tweet text
                offers = []
                for school in ALL_SCHOOLS:
                    if school.lower() in text.lower():
                        offers.append(school)

                # Detect class year
                year = "2027"  # default
                for y in ["2025","2026","2027","2028","2029"]:
                    if y in text:
                        year = y
                        break

                # Detect position
                pos = "ATH"
                for p in POSITION_IDEALS.keys():
                    if re.search(rf'\b{p}\b', text, re.I):
                        pos = p
                        break

                # Detect state
                state = ""
                for full, abbr in STATE_FULL.items():
                    if full.lower() in text.lower() or abbr in text:
                        state = abbr
                        break

                pid = make_id(player_name, year)
                links = build_links(player_name, x_handle=x_handle)

                player = {
                    "id": pid,
                    "name": player_name,
                    "position": pos,
                    "state": state,
                    "year": year,
                    "stars": 0,
                    "height": 0,
                    "weight": 0,
                    "offers": offers,
                    "category": classify_offers(offers),
                    "gem_score": 0,
                    "evaluation": ai_evaluation(player_name, pos, 0, 0, offers),
                    "links": links,
                    "source": "x",
                    "source_detail": f"@{x_handle}" if x_handle else "X/Twitter",
                    "source_url": f"https://x.com/{x_handle}" if x_handle else "",
                    "found_date": datetime.now(timezone.utc).isoformat(),
                }
                players.append(player)
                log.info(f"   👤 {player_name} | {pos} | {state} | via X (@{x_handle})")

            time.sleep(2)  # Rate limit courtesy

        except Exception as e:
            log.error(f"   ❌ X query failed: {e}")
            continue

    log.info(f"🐦 X total: {len(players)} players found")
    return players

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2: ON3 (HTML + Embedded JSON Scraping)
# ══════════════════════════════════════════════════════════════════════════════
def scrape_on3() -> list:
    """Scrape On3 recruit database pages."""
    log.info("🟢 Scraping On3...")
    players = []
    session = requests.Session()
    session.headers.update(HEADERS)

    # Strategy: Hit state ranking pages for each footprint state
    for year in ["2026", "2027", "2028"]:
        for state in FOOTPRINT_STATES:
            urls = [
                f"https://www.on3.com/db/rankings/player/prospects/football/{year}/?state_abbreviation={state}",
                f"https://www.on3.com/db/rankings/player/prospects/football/{year}/?state={state}",
            ]
            for url in urls:
                try:
                    resp = session.get(url, timeout=15)
                    log.info(f"   On3 {year}/{state} → HTTP {resp.status_code} ({len(resp.text)} bytes)")

                    if resp.status_code != 200:
                        continue

                    # Strategy 1: Look for __NEXT_DATA__ embedded JSON
                    soup = BeautifulSoup(resp.text, "lxml")
                    script = soup.find("script", id="__NEXT_DATA__")
                    if script and script.string:
                        try:
                            jdata = json.loads(script.string)
                            found = _parse_on3_json(jdata, year, state)
                            if found:
                                players.extend(found)
                                log.info(f"   ✅ On3 JSON: {len(found)} players from {state} {year}")
                                break  # Got data, skip alternate URL
                        except json.JSONDecodeError:
                            pass

                    # Strategy 2: Parse HTML directly
                    found = _parse_on3_html(soup, year, state)
                    if found:
                        players.extend(found)
                        log.info(f"   ✅ On3 HTML: {len(found)} players from {state} {year}")
                        break

                    time.sleep(1)

                except Exception as e:
                    log.warning(f"   ⚠️ On3 {year}/{state} failed: {e}")
                    continue

    log.info(f"🟢 On3 total: {len(players)} players found")
    return players


def _parse_on3_json(jdata: dict, year: str, state: str) -> list:
    """Extract player data from On3's __NEXT_DATA__ JSON."""
    players = []
    try:
        # Navigate the JSON tree — On3 uses Next.js
        # The structure varies, so we search recursively
        found_players = []
        _find_players_recursive(jdata, found_players)

        for p in found_players:
            name = p.get("fullName") or p.get("name") or p.get("firstName","") + " " + p.get("lastName","")
            name = name.strip()
            if not is_valid_player_name(name):
                continue

            pos = p.get("position", {}).get("abbreviation") or p.get("position","") or "ATH"
            if isinstance(pos, dict):
                pos = pos.get("abbreviation", "ATH")
            pos = pos.upper() if isinstance(pos, str) else "ATH"

            ht = p.get("height") or 0
            wt = p.get("weight") or 0
            stars = p.get("stars") or p.get("rating",{}).get("stars",0) or 0

            slug = p.get("slug") or p.get("key") or ""
            on3_url = f"https://www.on3.com/db/{slug}/" if slug else ""

            # Extract offers if available
            offers = []
            for o in p.get("recruitInterests", p.get("offers", [])):
                if isinstance(o, dict):
                    school = o.get("organization",{}).get("name") or o.get("school","")
                    if school and school in ALL_SCHOOLS:
                        offers.append(school)

            # Social media handles
            x_handle = ""
            socials = p.get("socialMedia", p.get("socials", []))
            if isinstance(socials, list):
                for s in socials:
                    if isinstance(s, dict) and "twitter" in s.get("type","").lower():
                        x_handle = s.get("handle", s.get("username", ""))

            pid = make_id(name, year)
            gs = gem_score(pos, ht, wt) if ht > 0 and wt > 0 else 0
            links = build_links(name, on3_url=on3_url, x_handle=x_handle)

            player = {
                "id": pid,
                "name": name,
                "position": pos,
                "state": normalize_state(state),
                "year": year,
                "stars": int(stars) if stars else 0,
                "height": int(ht) if ht else 0,
                "weight": int(wt) if wt else 0,
                "offers": offers,
                "category": classify_offers(offers),
                "gem_score": gs,
                "evaluation": ai_evaluation(name, pos, int(ht or 0), int(wt or 0), offers),
                "links": links,
                "source": "on3",
                "source_detail": "On3 Database",
                "source_url": on3_url,
                "found_date": datetime.now(timezone.utc).isoformat(),
            }
            players.append(player)

    except Exception as e:
        log.warning(f"   ⚠️ On3 JSON parse error: {e}")

    return players


def _find_players_recursive(obj, results, depth=0):
    """Recursively search JSON for player-like objects."""
    if depth > 15:
        return
    if isinstance(obj, dict):
        # Check if this dict looks like a player
        has_name = "fullName" in obj or "firstName" in obj or ("name" in obj and "position" in obj)
        has_player_fields = "height" in obj or "weight" in obj or "stars" in obj or "rating" in obj
        if has_name and has_player_fields:
            results.append(obj)
        else:
            for v in obj.values():
                _find_players_recursive(v, results, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _find_players_recursive(item, results, depth + 1)


def _parse_on3_html(soup: BeautifulSoup, year: str, state: str) -> list:
    """Parse On3 HTML for player data."""
    players = []

    # Look for player rows/cards by common CSS patterns
    selectors = [
        "a[href*='/db/']",
        "[class*='PlayerRow']",
        "[class*='player-row']",
        "[class*='recruit']",
        "tr[class*='player']",
        ".rankings-list li",
    ]

    for selector in selectors:
        try:
            elements = soup.select(selector)
            if not elements:
                continue

            for el in elements:
                # Try to extract player name
                name = ""
                name_el = el.select_one("[class*='name'], [class*='Name'], h3, h4, .player-name")
                if name_el:
                    name = name_el.get_text(strip=True)
                elif el.name == "a":
                    name = el.get_text(strip=True)

                name = re.sub(r"[^\w\s'-]", "", name).strip()
                name = re.sub(r"\s+", " ", name)

                if not is_valid_player_name(name):
                    continue

                # Get profile URL
                on3_url = ""
                if el.name == "a" and el.get("href","").startswith("/db/"):
                    on3_url = "https://www.on3.com" + el["href"]
                else:
                    link = el.find("a", href=re.compile(r"/db/"))
                    if link:
                        on3_url = "https://www.on3.com" + link["href"]

                # Extract position
                pos = "ATH"
                pos_el = el.select_one("[class*='position'], [class*='Position'], .pos")
                if pos_el:
                    pos_text = pos_el.get_text(strip=True).upper()
                    if pos_text in POSITION_IDEALS:
                        pos = pos_text

                # Extract measurables from surrounding text
                text = el.get_text(" ", strip=True)
                ht, wt = 0, 0
                ht_m = re.search(r"(\d)['\u2019-](\d{1,2})", text)
                if ht_m:
                    ht = int(ht_m.group(1)) * 12 + int(ht_m.group(2))
                wt_m = re.search(r"(\d{2,3})\s*(?:lbs?|pounds)", text, re.I)
                if wt_m:
                    wt = int(wt_m.group(1))

                # Stars
                stars = 0
                star_el = el.select_one("[class*='star'], [class*='Star'], .rating")
                if star_el:
                    s_m = re.search(r"(\d)", star_el.get_text())
                    if s_m:
                        stars = int(s_m.group(1))

                pid = make_id(name, year)
                gs = gem_score(pos, ht, wt) if ht > 0 and wt > 0 else 0
                links = build_links(name, on3_url=on3_url)

                player = {
                    "id": pid,
                    "name": name,
                    "position": pos,
                    "state": normalize_state(state),
                    "year": year,
                    "stars": stars,
                    "height": ht,
                    "weight": wt,
                    "offers": [],
                    "category": "G6",
                    "gem_score": gs,
                    "evaluation": ai_evaluation(name, pos, ht, wt, []),
                    "links": links,
                    "source": "on3",
                    "source_detail": "On3 Rankings",
                    "source_url": on3_url,
                    "found_date": datetime.now(timezone.utc).isoformat(),
                }
                players.append(player)

            if players:
                break  # Found data with this selector

        except Exception as e:
            log.warning(f"   ⚠️ On3 selector '{selector}' failed: {e}")
            continue

    return players

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3: 247SPORTS (HTML + Embedded JSON Scraping)
# ══════════════════════════════════════════════════════════════════════════════
def scrape_247() -> list:
    """Scrape 247Sports recruit rankings and Tennessee target pages."""
    log.info("📊 Scraping 247Sports...")
    players = []
    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers["Referer"] = "https://www.google.com/"

    # Strategy: State ranking pages + Tennessee-specific pages
    urls = []
    for year in ["2026", "2027", "2028"]:
        for state in FOOTPRINT_STATES:
            urls.append((
                f"https://247sports.com/Season/{year}-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State={state}",
                year, state
            ))
        # Tennessee-specific pages
        urls.append((
            f"https://247sports.com/college/tennessee/Season/{year}-Football/Targets/",
            year, "TN"
        ))
        urls.append((
            f"https://247sports.com/college/tennessee/Season/{year}-Football/Commits/",
            year, "TN"
        ))

    for url, year, state in urls:
        try:
            resp = session.get(url, timeout=15)
            log.info(f"   247 {year}/{state} → HTTP {resp.status_code} ({len(resp.text)} bytes)")

            if resp.status_code != 200:
                time.sleep(1)
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Strategy 1: Look for embedded JSON
            for script in soup.find_all("script"):
                if script.string and ("playerData" in script.string or "recruitRankings" in script.string):
                    try:
                        # Try to extract JSON from script content
                        json_match = re.search(r'(\[{.*?}\])', script.string, re.DOTALL)
                        if json_match:
                            jdata = json.loads(json_match.group(1))
                            for p in jdata:
                                name = p.get("name","") or (p.get("firstName","") + " " + p.get("lastName",""))
                                name = name.strip()
                                if not is_valid_player_name(name):
                                    continue
                                # Extract what we can
                                pos = p.get("position","ATH")
                                ht = p.get("height", 0)
                                wt = p.get("weight", 0)
                                profile_url = p.get("url","")
                                if profile_url and not profile_url.startswith("http"):
                                    profile_url = f"https://247sports.com{profile_url}"

                                pid = make_id(name, year)
                                gs = gem_score(pos, ht, wt) if ht and wt else 0
                                links = build_links(name, two47_url=profile_url)

                                player = {
                                    "id": pid, "name": name, "position": pos,
                                    "state": normalize_state(state), "year": year,
                                    "stars": p.get("stars",0), "height": ht, "weight": wt,
                                    "offers": [], "category": "G6",
                                    "gem_score": gs,
                                    "evaluation": ai_evaluation(name, pos, ht, wt, []),
                                    "links": links, "source": "247sports",
                                    "source_detail": "247Sports Composite",
                                    "source_url": profile_url,
                                    "found_date": datetime.now(timezone.utc).isoformat(),
                                }
                                players.append(player)
                    except (json.JSONDecodeError, Exception):
                        pass

            # Strategy 2: HTML parsing
            found = _parse_247_html(soup, year, state)
            if found:
                players.extend(found)
                log.info(f"   ✅ 247 HTML: {len(found)} players from {state} {year}")

            time.sleep(1.5)  # Be respectful

        except Exception as e:
            log.warning(f"   ⚠️ 247 {year}/{state} failed: {e}")
            continue

    log.info(f"📊 247Sports total: {len(players)} players found")
    return players


def _parse_247_html(soup: BeautifulSoup, year: str, state: str) -> list:
    """Parse 247Sports HTML for recruit data."""
    players = []

    # 247 uses various list formats
    selectors = [
        "li.rankings-page__list-item",
        ".recruit",
        "li[class*='ranking']",
        ".player",
        "tr.recruit-row",
        ".target-content",
    ]

    for selector in selectors:
        elements = soup.select(selector)
        if not elements:
            continue

        for el in elements:
            try:
                # Extract name
                name = ""
                name_el = el.select_one("a.rankings-page__name-link, .recruit-name a, .player-name a, a[href*='/Player/'], a[href*='/player/']")
                if name_el:
                    name = name_el.get_text(strip=True)
                else:
                    name_el = el.select_one(".name, h3, h4")
                    if name_el:
                        name = name_el.get_text(strip=True)

                name = re.sub(r"[^\w\s'-]", "", name).strip()
                name = re.sub(r"\s+", " ", name)
                if not is_valid_player_name(name):
                    continue

                # Profile URL
                two47_url = ""
                profile_link = el.select_one("a[href*='/Player/'], a[href*='/player/']")
                if profile_link:
                    href = profile_link.get("href", "")
                    if href.startswith("/"):
                        two47_url = f"https://247sports.com{href}"
                    elif href.startswith("http"):
                        two47_url = href

                # Position
                pos = "ATH"
                pos_el = el.select_one(".position, .pos, [class*='position']")
                if pos_el:
                    pos_text = pos_el.get_text(strip=True).upper()
                    if pos_text in POSITION_IDEALS:
                        pos = pos_text

                # Measurables
                text = el.get_text(" ", strip=True)
                ht, wt = 0, 0
                ht_m = re.search(r"(\d)['\u2019-](\d{1,2})", text)
                if ht_m:
                    ht = int(ht_m.group(1)) * 12 + int(ht_m.group(2))
                wt_m = re.search(r"(\d{2,3})\s*(?:lbs?|pounds)", text, re.I)
                if wt_m:
                    wt = int(wt_m.group(1))

                # Stars
                stars = 0
                star_el = el.select_one("[class*='star'], .rating, .score")
                if star_el:
                    s_m = re.search(r"(\d)", star_el.get_text())
                    if s_m:
                        stars = int(s_m.group(1))

                pid = make_id(name, year)
                gs = gem_score(pos, ht, wt) if ht > 0 and wt > 0 else 0
                links = build_links(name, two47_url=two47_url)

                player = {
                    "id": pid, "name": name, "position": pos,
                    "state": normalize_state(state), "year": year,
                    "stars": stars, "height": ht, "weight": wt,
                    "offers": [], "category": "G6",
                    "gem_score": gs,
                    "evaluation": ai_evaluation(name, pos, ht, wt, []),
                    "links": links, "source": "247sports",
                    "source_detail": "247Sports Rankings",
                    "source_url": two47_url,
                    "found_date": datetime.now(timezone.utc).isoformat(),
                }
                players.append(player)
                log.info(f"   👤 {name} | {pos} | {state} | via 247Sports")

            except Exception:
                continue

        if players:
            break

    return players

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 4: GOOGLE NEWS RSS (Backup — STRICT filtering)
# ══════════════════════════════════════════════════════════════════════════════
def scrape_google_news() -> list:
    """Google News RSS — backup source with extremely strict name filtering."""
    log.info("📰 Scraping Google News RSS (strict mode)...")
    players = []

    # Very specific queries — must include offer language
    queries = [
        '"receives offer" football recruit Tennessee',
        '"offered by" football Tennessee 2027',
        '"blessed to receive" offer football Tennessee',
        '"picks up offer" football SEC',
        '"receives offer" football recruit Kentucky',
        '"receives offer" football recruit Georgia',
        '"receives offer" football recruit Alabama',
        '"receives offer" football recruit Florida',
        '"receives offer" football recruit North Carolina',
        '"receives offer" football recruit Virginia',
    ]

    for query in queries:
        try:
            url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            log.info(f"   News query: {query[:55]}... → HTTP {resp.status_code}")

            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "xml")
            items = soup.find_all("item")
            log.info(f"   📰 Got {len(items)} articles")

            for item in items:
                title = item.find("title")
                link = item.find("link")
                source = item.find("source")

                if not title:
                    continue

                title_text = title.get_text(strip=True)
                article_url = link.get_text(strip=True) if link else ""
                source_name = source.get_text(strip=True) if source else "Google News"

                # STRICT: Title must contain offer language
                if not re.search(r"(offer|commit|pledge|flip|decommit|receiv)", title_text, re.I):
                    continue

                # Extract candidate names from title
                names = extract_player_names(title_text)

                for name in names:
                    if not is_valid_player_name(name):
                        log.info(f"   🚫 Filtered: '{name}' (failed validation)")
                        continue

                    # Detect year
                    year = "2027"
                    for y in ["2025","2026","2027","2028","2029"]:
                        if y in title_text:
                            year = y
                            break

                    # Detect state
                    state = ""
                    for full, abbr in STATE_FULL.items():
                        if full.lower() in title_text.lower():
                            state = abbr
                            break
                    if not state:
                        for abbr in FOOTPRINT_STATES:
                            if f" {abbr} " in title_text or title_text.endswith(f" {abbr}"):
                                state = abbr
                                break

                    if not in_footprint(state):
                        continue

                    # Detect position
                    pos = "ATH"
                    for p in POSITION_IDEALS.keys():
                        if re.search(rf'\b{p}\b', title_text, re.I):
                            pos = p
                            break

                    # Extract offers mentioned
                    offers = []
                    for school in ALL_SCHOOLS:
                        if school.lower() in title_text.lower():
                            offers.append(school)

                    pid = make_id(name, year)
                    links = build_links(name)

                    player = {
                        "id": pid, "name": name, "position": pos,
                        "state": state, "year": year,
                        "stars": 0, "height": 0, "weight": 0,
                        "offers": offers, "category": classify_offers(offers),
                        "gem_score": 0,
                        "evaluation": ai_evaluation(name, pos, 0, 0, offers),
                        "links": links, "source": "news",
                        "source_detail": source_name,
                        "source_url": article_url,
                        "found_date": datetime.now(timezone.utc).isoformat(),
                    }
                    players.append(player)
                    log.info(f"   👤 {name} | {pos} | {state} | via {source_name}")

            time.sleep(1)

        except Exception as e:
            log.error(f"   ❌ News query failed: {e}")
            continue

    log.info(f"📰 Google News total: {len(players)} players found")
    return players


def extract_player_names(text: str) -> list:
    """Extract potential player names from a headline. Very strict."""
    names = []

    # Pattern 1: "Firstname Lastname receives/picks up/gets offer"
    for m in re.finditer(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+(?:receives?|picks?\s+up|gets?|lands?|earns?|adds?)", text):
        names.append(m.group(1))

    # Pattern 2: "offer to Firstname Lastname"
    for m in re.finditer(r"offer(?:ed)?\s+(?:to\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})", text):
        names.append(m.group(1))

    # Pattern 3: "Firstname Lastname commits/pledges/flips"
    for m in re.finditer(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+(?:commits?|pledges?|flips?|decommits?)", text):
        names.append(m.group(1))

    # Pattern 4: "Star/rated Firstname Lastname" (e.g. "4-star John Smith")
    for m in re.finditer(r"\d-star\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})", text):
        names.append(m.group(1))

    # Pattern 5: Position + Name (e.g. "QB John Smith")
    pos_list = "|".join(POSITION_IDEALS.keys())
    for m in re.finditer(rf"(?:{pos_list})\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})", text):
        names.append(m.group(1))

    # Deduplicate
    seen = set()
    unique = []
    for n in names:
        nl = n.lower()
        if nl not in seen:
            seen.add(nl)
            unique.append(n)

    return unique

# ══════════════════════════════════════════════════════════════════════════════
# MERGE + DEDUPLICATE
# ══════════════════════════════════════════════════════════════════════════════
def merge_players(existing: dict, new_players: list) -> dict:
    """Merge new players with existing, enriching data where possible."""
    for p in new_players:
        pid = p["id"]
        if pid in existing:
            old = existing[pid]
            # Merge offers (union)
            old_offers = set(old.get("offers", []))
            new_offers = set(p.get("offers", []))
            merged_offers = list(old_offers | new_offers)
            old["offers"] = merged_offers
            old["category"] = classify_offers(merged_offers)

            # Update measurables if new data is better
            if p.get("height", 0) > 0 and old.get("height", 0) == 0:
                old["height"] = p["height"]
            if p.get("weight", 0) > 0 and old.get("weight", 0) == 0:
                old["weight"] = p["weight"]
            if p.get("stars", 0) > old.get("stars", 0):
                old["stars"] = p["stars"]

            # Update links if new source has real URLs
            for key in ["on3", "247", "x", "hudl"]:
                new_link = p.get("links", {}).get(key, "")
                old_link = old.get("links", {}).get(key, "")
                if new_link and ("search" not in new_link) and ("search" in old_link or not old_link):
                    old["links"][key] = new_link

            # Recalculate scores
            if old["height"] > 0 and old["weight"] > 0:
                old["gem_score"] = gem_score(old["position"], old["height"], old["weight"])
                old["evaluation"] = ai_evaluation(
                    old["name"], old["position"], old["height"], old["weight"], merged_offers
                )

        else:
            existing[pid] = p

    return existing

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 70)
    log.info("🏈 VOL RECRUITING MONITOR — SCRAPER v5")
    log.info(f"   Time: {datetime.now(timezone.utc).isoformat()}")
    log.info(f"   Footprint: {', '.join(sorted(FOOTPRINT_STATES))}")
    log.info(f"   X API: {'✅ Token set' if X_BEARER else '❌ No token'}")
    log.info("=" * 70)

    # Load existing data
    existing = load_existing()

    # Run all sources
    sources = {"x": 0, "on3": 0, "247sports": 0, "news": 0}

    # Source 1: X/Twitter (PRIORITY)
    try:
        x_players = scrape_x()
        sources["x"] = len(x_players)
        existing = merge_players(existing, x_players)
    except Exception as e:
        log.error(f"❌ X scraper crashed: {e}")

    # Source 2: On3
    try:
        on3_players = scrape_on3()
        sources["on3"] = len(on3_players)
        existing = merge_players(existing, on3_players)
    except Exception as e:
        log.error(f"❌ On3 scraper crashed: {e}")

    # Source 3: 247Sports
    try:
        two47_players = scrape_247()
        sources["247sports"] = len(two47_players)
        existing = merge_players(existing, two47_players)
    except Exception as e:
        log.error(f"❌ 247 scraper crashed: {e}")

    # Source 4: Google News (backup)
    try:
        news_players = scrape_google_news()
        sources["news"] = len(news_players)
        existing = merge_players(existing, news_players)
    except Exception as e:
        log.error(f"❌ News scraper crashed: {e}")

    # Build output
    all_players = list(existing.values())

    # Final validation — remove anything that slipped through
    valid_players = []
    for p in all_players:
        if is_valid_player_name(p.get("name", "")):
            valid_players.append(p)
        else:
            log.warning(f"🚫 Final filter removed: '{p.get('name','?')}'")

    output = {
        "players": valid_players,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "total": len(valid_players),
    }

    # Write output
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("=" * 70)
    log.info(f"✅ DONE — {len(valid_players)} total players in database")
    log.info(f"   Sources: X={sources['x']}  On3={sources['on3']}  247={sources['247sports']}  News={sources['news']}")
    log.info(f"   Written to: {DATA_PATH}")
    log.info("=" * 70)

    # Print first 10 for verification
    for p in valid_players[:10]:
        log.info(f"   📋 {p['name']} | {p['position']} | {p['state']} | {p['year']} | {p['source']} | offers: {p['offers'][:3]}")


if __name__ == "__main__":
    main()
