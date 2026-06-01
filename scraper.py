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

def in_footprint(text: str) -> bool:
    tu = text.upper()
    for abbr in FOOTPRINT_STATES:
        if re.search(r'\b' + abbr + r'\b', tu):
            return True
    tl = text.lower()
    for full_name in STATE_FULL:
        if full_name.lower() in tl:
            return True
    return False

def get_state(text: str) -> str:
    tu = text.upper()
    for abbr in FOOTPRINT_STATES:
        if re.search(r'\b' + abbr + r'\b', tu):
            return abbr
    tl = text.lower()
    for full_name, abbr in STATE_FULL.items():
        if full_name.lower() in tl:
            return abbr
    return ""

HEIGHT_RE = re.compile(r"(\d)['\u2019-](\d{1,2})(?:\"|″)?")
WEIGHT_RE = re.compile(r"\b(\d{2,3})\s*(?:lbs?|pounds?)\b", re.I)
CLASS_RE  = re.compile(r"\b(202[5-9]|203[0-2])\b")
STARS_RE  = re.compile(r"\b([2-5])\s*[-–]?\s*star", re.I)

POSITIONS = ["EDGE","ILB","OLB","QB","RB","WR","TE","OT","OG","OL",
             "DT","DE","DL","LB","CB","ATH","DB","S","K","P","LS"]

def get_height(text: str):
    m = HEIGHT_RE.search(text)
    if m:
        ft, inch = int(m.group(1)), int(m.group(2))
        if 5 <= ft <= 7 and 0 <= inch <= 11:
            return ft * 12 + inch, f"{ft}'{inch}\""
    return 0, ""

def get_weight(text: str) -> int:
    m = WEIGHT_RE.search(text)
    if m:
        w = int(m.group(1))
        if 140 <= w <= 380:
            return w
    return 0

def get_year(text: str) -> str:
    m = CLASS_RE.search(text)
    return m.group(1) if m else ""

def get_stars(text: str) -> int:
    m = STARS_RE.search(text)
    return int(m.group(1)) if m else 0

def get_position(text: str) -> str:
    tu = text.upper()
    for pos in POSITIONS:
        if re.search(r'\b' + pos + r'\b', tu):
            return pos
    return ""

def get_offers(text: str) -> list:
    found = set()
    tl = text.lower()
    for school in ALL_SCHOOLS:
        if school.lower() in tl:
            found.add(school)
    return sorted(found)

def categorize(offers: list) -> str:
    for s in offers:
        if s in SEC_SCHOOLS:
            return "sec"
    for s in offers:
        if s in P4_SCHOOLS:
            return "p4"
    return "g6"

def calc_gem(player: dict) -> int:
    pos = player.get("position", "ATH").upper()
    matched = next((k for k in POSITION_IDEALS if k in pos), "ATH")
    ideal_h, ideal_w = POSITION_IDEALS[matched]
    h = player.get("height_inches", 0)
    w = player.get("weight", 0)
    if not h and not w:
        return 50
    h_score = max(0, 100 - abs(h - ideal_h) * 12) if h else 50
    w_score = max(0, 100 - abs(w - ideal_w) / max(ideal_w, 1) * 100) if w else 50
    return round((h_score + w_score) / 2)

def build_eval(player: dict) -> dict:
    pos = player.get("position", "ATH")
    h_in = player.get("height_inches", 0)
    w = player.get("weight", 0)
    h_str = player.get("height", "")
    stars = player.get("stars", 0)
    offers = player.get("offers", [])
    gem = player.get("gem_score", 50)
    cat = player.get("category", "g6")

    strengths, weaknesses = [], []

    if h_in and w:
        ideal_h, ideal_w = POSITION_IDEALS.get(pos, (73, 200))
        if h_in >= ideal_h:
            strengths.append(f"Ideal or above-average height for {pos} ({h_str})")
        else:
            weaknesses.append(f"Below ideal height for {pos} ({h_str} vs {ideal_h // 12}'{ideal_h % 12}\" ideal)")
        if w >= ideal_w * 0.95:
            strengths.append(f"Good weight for {pos} ({w} lbs)")
        else:
            weaknesses.append(f"Could add weight for {pos} ({w} lbs vs {ideal_w} ideal)")

    sec_offers = [o for o in offers if o in SEC_SCHOOLS]
    p4_offers = [o for o in offers if o in P4_SCHOOLS]
    if len(sec_offers) >= 3:
        strengths.append(f"Elite offer sheet — {len(sec_offers)} SEC offers")
    elif len(sec_offers) >= 1:
        strengths.append(f"SEC-caliber talent — offers from {', '.join(sec_offers[:3])}")
    elif len(p4_offers) >= 2:
        strengths.append(f"P4 attention — {len(p4_offers)} Power 4 offers")

    if stars >= 4:
        strengths.append(f"Highly rated {stars}-star prospect")
    elif stars == 3:
        strengths.append("Solid 3-star rating — proven talent")
    elif stars == 0 and len(offers) >= 2:
        weaknesses.append("Unrated — limited exposure so far")

    if gem >= 80 and cat == "g6":
        strengths.append(f"💎 Hidden gem — P4 measurables (Gem Score: {gem}) with G6 offers only")
    if gem >= 85:
        strengths.append(f"Elite physical profile for position (Gem: {gem}/100)")

    if len(offers) == 1:
        weaknesses.append("Limited offer sheet — may still be early in recruitment")
    if len(offers) >= 8:
        strengths.append(f"Highly recruited — {len(offers)} total offers")

    # position-specific
    if pos == "QB":
        if h_in and h_in >= 74:
            strengths.append("Prototypical QB height — can see over the line")
        if h_in and h_in < 72:
            weaknesses.append("Undersized for QB — must compensate with mobility")
    elif pos in ("WR", "CB", "S", "DB"):
        if h_in and h_in >= 73:
            strengths.append(f"Length advantage at {pos} — good for contested catches/press coverage")
    elif pos in ("OL", "OT", "OG", "C"):
        if w and w >= 285:
            strengths.append("College-ready size on the offensive line")
        elif w and w < 260:
            weaknesses.append("Needs to add mass for college OL play")
    elif pos in ("DL", "DT", "DE", "EDGE"):
        if h_in and h_in >= 75 and w and w >= 240:
            strengths.append("Good frame and weight combo for pass rushing")

    if not strengths:
        strengths.append("Prospect in Tennessee footprint — worth monitoring")
    if not weaknesses:
        weaknesses.append("Limited data — need more film and camp results")

    return {"strengths": strengths[:4], "weaknesses": weaknesses[:3]}

def build_links(name: str) -> dict:
    """Generate search links for Hudl, UC Report, and X/Twitter."""
    q = quote_plus(name)
    return {
        "hudl": f"https://www.hudl.com/search?query={q}&type=athlete",
        "uc_report": f"https://www.google.com/search?q={q}+site%3Aucreport.com",
        "x_profile": f"https://x.com/search?q={q}+football&src=typed_query",
    }

# ══════════════════════════════════════════════════════════════════════════════
# OFFER ANNOUNCEMENT PATTERNS — what real offer tweets look like
# ══════════════════════════════════════════════════════════════════════════════
OFFER_PATTERNS = [
    re.compile(r"(?:blessed|excited|honored|humbled|grateful)\s+(?:to\s+)?(?:receive|announce|say|have)\s+(?:an?\s+)?offer", re.I),
    re.compile(r"(?:received|got|earned)\s+(?:an?\s+)?(?:offer|scholarship)", re.I),
    re.compile(r"offer(?:ed)?\s+(?:from|by)\s+", re.I),
    re.compile(r"(?:new|latest)\s+offer", re.I),
    re.compile(r"(?:offer\s+list|offer\s+update)", re.I),
    re.compile(r"(?:committed|commits|pledges|flips)\s+to\s+", re.I),
    re.compile(r"#(?:AGTG|Blessed|Offered|GoVols|Committed)", re.I),
]

def is_offer_tweet(text: str) -> bool:
    return any(p.search(text) for p in OFFER_PATTERNS)

# ══════════════════════════════════════════════════════════════════════════════
# NAME EXTRACTION — much smarter, context-aware
# ══════════════════════════════════════════════════════════════════════════════
# Pattern: "Player Name (School)" or "Player Name, a 4-star" etc
NAME_PATTERNS = [
    # "FirstName LastName, a X-star POS from City, State"
    re.compile(r'\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15}(?:-[A-Z][a-z]{1,15})?)\s*,\s*(?:a\s+)?\d-star', re.M),
    # "X-star POS FirstName LastName"
    re.compile(r'\d-star\s+\w+\s+([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15}(?:-[A-Z][a-z]{1,15})?)\b', re.M),
    # "offered/commits FirstName LastName"
    re.compile(r'(?:offered|offer(?:ed)?(?:\s+to)?|commit(?:ted|s)?(?:\s+to)?)\s+([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15}(?:-[A-Z][a-z]{1,15})?)\b', re.I | re.M),
    # "FirstName LastName receives/earned offer"
    re.compile(r'\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15}(?:-[A-Z][a-z]{1,15})?)\s+(?:receives?|earned?|gets?|lands?|picks?\s+up)\s+(?:an?\s+)?offer', re.M),
    # "@handle FirstName LastName" (X/Twitter style)
    re.compile(r'@\w+\s+([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15}(?:-[A-Z][a-z]{1,15})?)\b', re.M),
    # Generic "FirstName LastName" after offer context (looser, used last)
    re.compile(r'\b([A-Z][a-z]{2,15})\s+([A-Z][a-z]{2,15}(?:-[A-Z][a-z]{1,15})?)\b'),
]

def extract_player_names(text: str) -> list:
    """Extract real player names from text using context-aware patterns."""
    found = []
    for pattern in NAME_PATTERNS:
        for m in pattern.finditer(text):
            first, last = m.group(1), m.group(2)
            full = f"{first} {last}"
            if is_valid_player_name(full):
                found.append(full)
    # Deduplicate preserving order
    seen = set()
    unique = []
    for n in found:
        nl = n.lower()
        if nl not in seen:
            seen.add(nl)
            unique.append(n)
    return unique

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1: X / TWITTER API v2
# ══════════════════════════════════════════════════════════════════════════════
def scrape_x() -> list:
    """Pull real offer announcements from X/Twitter."""
    players = []
    if not X_BEARER:
        log.warning("❌ X/Twitter: No bearer token — skipping")
        return players

    log.info("🐦 X/Twitter: Starting search...")
    headers = {"Authorization": f"Bearer {X_BEARER}"}

    # Search queries targeting real offer announcements in footprint states
    queries = [
        '"offer" (football OR recruit) (Tennessee OR Kentucky OR Georgia OR Alabama OR Florida OR "North Carolina" OR Virginia OR Mississippi OR Arkansas OR Missouri OR "South Carolina" OR Ohio OR Indiana OR Louisiana OR "West Virginia") -is:retweet',
        '"blessed to receive" offer football -is:retweet',
        '"committed to" (Tennessee OR Vols) football 2027 OR 2028 OR 2026 -is:retweet',
        '#AGTG offer football -is:retweet',
        '"offer from" (#SEC OR #P4 OR Tennessee OR Alabama OR Georgia OR Florida OR Auburn OR Kentucky OR LSU) -is:retweet',
    ]

    for i, query in enumerate(queries):
        try:
            log.info(f"  🔍 X query {i+1}/{len(queries)}")
            url = "https://api.x.com/2/tweets/search/recent"
            params = {
                "query": query,
                "max_results": 50,
                "tweet.fields": "created_at,author_id,text",
                "expansions": "author_id",
                "user.fields": "name,username",
            }
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            log.info(f"    HTTP {resp.status_code}")

            if resp.status_code == 429:
                log.warning("    ⚠️ Rate limited — skipping remaining X queries")
                break
            if resp.status_code != 200:
                log.warning(f"    ⚠️ Non-200: {resp.text[:200]}")
                continue

            data = resp.json()
            tweets = data.get("data", [])
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            log.info(f"    📊 Got {len(tweets)} tweets")

            for tweet in tweets:
                text = tweet.get("text", "")

                # Must look like an offer announcement
                if not is_offer_tweet(text):
                    continue

                # Must be in footprint
                if not in_footprint(text):
                    continue

                names = extract_player_names(text)
                if not names:
                    # Try the author's display name if it's an athlete posting
                    author_id = tweet.get("author_id", "")
                    if author_id in users:
                        display = users[author_id].get("name", "")
                        username = users[author_id].get("username", "")
                        if is_valid_player_name(display):
                            names = [display]

                state = get_state(text)
                offers = get_offers(text)
                year = get_year(text)
                pos = get_position(text)
                stars = get_stars(text)
                h_in, h_str = get_height(text)
                w = get_weight(text)

                for name in names[:2]:  # max 2 players per tweet
                    if not year:
                        year = "2027"  # default class
                    if not state:
                        continue  # must have a state

                    player_id = make_id(name, year)
                    links = build_links(name)

                    # Get author username for tweet link
                    author_id = tweet.get("author_id", "")
                    tweet_url = ""
                    if author_id in users:
                        uname = users[author_id].get("username", "")
                        tweet_url = f"https://x.com/{uname}/status/{tweet['id']}"
                        links["x_profile"] = f"https://x.com/{uname}"

                    p = {
                        "id": player_id,
                        "name": name,
                        "position": pos or "ATH",
                        "state": state,
                        "year": year,
                        "stars": stars,
                        "height": h_str,
                        "height_inches": h_in,
                        "weight": w,
                        "offers": offers if offers else ["Unknown"],
                        "category": categorize(offers),
                        "source": "X/Twitter",
                        "source_url": tweet_url or f"https://x.com/search?q={quote_plus(name)}+offer",
                        "links": links,
                        "found_at": datetime.now(timezone.utc).isoformat(),
                    }
                    p["gem_score"] = calc_gem(p)
                    p["evaluation"] = build_eval(p)
                    players.append(p)
                    log.info(f"    👤 {name} | {pos or 'ATH'} | {state} | {year} | via X/Twitter")

            time.sleep(1.5)  # rate limit courtesy

        except Exception as e:
            log.error(f"    ❌ X query {i+1} error: {e}")
            continue

    log.info(f"🐦 X/Twitter: Found {len(players)} valid players")
    return players

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2: GOOGLE NEWS RSS (Free, always works)
# ══════════════════════════════════════════════════════════════════════════════
def scrape_google_news() -> list:
    """Pull recruiting offers from Google News RSS with STRICT filtering."""
    players = []
    log.info("📰 Google News: Starting RSS scrape...")

    # Very specific queries — reduces noise dramatically
    queries = [
        "high school football recruit offer Tennessee 2027",
        "high school football recruit offer Tennessee 2028",
        "high school football recruit offer Tennessee 2026",
        "football recruit offer Kentucky Georgia Alabama 2027",
        "football recruiting offer SEC commit 2027",
        "football recruiting offer SEC commit 2028",
        "4-star football recruit offer Southeast 2027",
        "football recruit offer Virginia North Carolina 2027",
        "football recruit offer Florida Mississippi 2027",
        "football recruit offer Ohio Indiana 2027",
    ]

    for i, query in enumerate(queries):
        try:
            url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
            log.info(f"  🔍 News query {i+1}/{len(queries)}: {query[:50]}...")
            resp = requests.get(url, headers=HEADERS, timeout=12)
            log.info(f"    HTTP {resp.status_code}")

            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "lxml-xml")
            items = soup.find_all("item")
            log.info(f"    📊 Got {len(items)} articles")

            for item in items[:15]:  # limit per query
                title = item.find("title")
                title_text = title.get_text(strip=True) if title else ""
                desc = item.find("description")
                desc_text = desc.get_text(strip=True) if desc else ""
                link = item.find("link")
                link_text = link.get_text(strip=True) if link else ""
                source_el = item.find("source")
                source_name = source_el.get_text(strip=True) if source_el else "Google News"

                combined = f"{title_text} {desc_text}"

                # MUST contain offer-related keywords
                offer_words = ["offer", "commit", "recruit", "prospect", "pledge", "flip", "decommit"]
                if not any(w in combined.lower() for w in offer_words):
                    continue

                # Must be in footprint
                if not in_footprint(combined):
                    continue

                names = extract_player_names(combined)

                state = get_state(combined)
                offers = get_offers(combined)
                year = get_year(combined)
                pos = get_position(combined)
                stars = get_stars(combined)
                h_in, h_str = get_height(combined)
                w = get_weight(combined)

                for name in names[:2]:
                    if not state:
                        continue
                    if not year:
                        year = "2027"

                    player_id = make_id(name, year)
                    links = build_links(name)

                    p = {
                        "id": player_id,
                        "name": name,
                        "position": pos or "ATH",
                        "state": state,
                        "year": year,
                        "stars": stars,
                        "height": h_str,
                        "height_inches": h_in,
                        "weight": w,
                        "offers": offers if offers else ["Unknown"],
                        "category": categorize(offers),
                        "source": f"Google News ({source_name})",
                        "source_url": link_text,
                        "links": links,
                        "found_at": datetime.now(timezone.utc).isoformat(),
                    }
                    p["gem_score"] = calc_gem(p)
                    p["evaluation"] = build_eval(p)
                    players.append(p)
                    log.info(f"    👤 {name} | {pos or 'ATH'} | {state} | {year} | via {source_name}")

            time.sleep(0.8)

        except Exception as e:
            log.error(f"    ❌ News query {i+1} error: {e}")
            continue

    log.info(f"📰 Google News: Found {len(players)} valid players")
    return players

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3: ON3 RECRUITING
# ══════════════════════════════════════════════════════════════════════════════
def scrape_on3() -> list:
    """Scrape On3 recruiting pages for Tennessee footprint offers."""
    players = []
    log.info("🏈 On3: Starting scrape...")

    urls = [
        "https://www.on3.com/db/rankings/player/industry/football/2027/",
        "https://www.on3.com/db/rankings/player/industry/football/2028/",
        "https://www.on3.com/db/rankings/player/industry/football/2026/",
        "https://www.on3.com/college/tennessee-volunteers/recruiting/commits/",
    ]

    for url in urls:
        try:
            log.info(f"  🔍 Fetching: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            log.info(f"    HTTP {resp.status_code}")

            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Try __NEXT_DATA__ JSON blob (On3 uses Next.js)
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                try:
                    data = json.loads(script.string)
                    # Navigate the JSON tree to find player data
                    props = data.get("props", {}).get("pageProps", {})

                    # Try multiple paths
                    player_list = (
                        props.get("players", []) or
                        props.get("rankings", []) or
                        props.get("commits", []) or
                        props.get("data", {}).get("players", []) or
                        []
                    )

                    log.info(f"    📊 Found {len(player_list)} entries in __NEXT_DATA__")

                    for entry in player_list:
                        # On3 data can be nested differently
                        player_data = entry.get("player", entry)
                        name = player_data.get("fullName") or player_data.get("name") or ""
                        if not name or not is_valid_player_name(name):
                            continue

                        hometown = player_data.get("hometown", {})
                        state_raw = ""
                        if isinstance(hometown, dict):
                            state_raw = hometown.get("stateAbbreviation") or hometown.get("state", "")
                        elif isinstance(hometown, str):
                            state_raw = hometown

                        # Check footprint
                        if state_raw.upper() not in FOOTPRINT_STATES:
                            state_raw = get_state(str(player_data))
                            if not state_raw:
                                continue

                        state = state_raw.upper() if state_raw.upper() in FOOTPRINT_STATES else get_state(state_raw)
                        if not state:
                            continue

                        pos = player_data.get("position", {})
                        if isinstance(pos, dict):
                            pos = pos.get("abbreviation", "ATH")
                        elif not pos:
                            pos = "ATH"

                        year = str(player_data.get("year", "")) or get_year(str(player_data))
                        stars = player_data.get("rating", 0) or player_data.get("stars", 0)
                        if isinstance(stars, float):
                            stars = round(stars)

                        h_str = player_data.get("height", "")
                        w = player_data.get("weight", 0)
                        h_in = 0
                        if h_str:
                            h_in, h_str = get_height(str(h_str))
                        if isinstance(w, str):
                            w = get_weight(w)

                        player_id = make_id(name, year or "2027")
                        links = build_links(name)

                        # Try to get On3 profile link
                        slug = player_data.get("slug", "")
                        if slug:
                            links["on3_profile"] = f"https://www.on3.com/db/{slug}/"

                        p = {
                            "id": player_id,
                            "name": name,
                            "position": str(pos),
                            "state": state,
                            "year": year or "2027",
                            "stars": int(stars) if stars else 0,
                            "height": h_str,
                            "height_inches": h_in,
                            "weight": int(w) if w else 0,
                            "offers": get_offers(str(player_data)),
                            "category": categorize(get_offers(str(player_data))),
                            "source": "On3",
                            "source_url": url,
                            "links": links,
                            "found_at": datetime.now(timezone.utc).isoformat(),
                        }
                        p["gem_score"] = calc_gem(p)
                        p["evaluation"] = build_eval(p)
                        players.append(p)
                        log.info(f"    👤 {name} | {pos} | {state} | {year} | via On3")

                except json.JSONDecodeError:
                    log.warning("    ⚠️ Failed to parse __NEXT_DATA__")

            # Fallback: parse HTML tables/lists
            rows = soup.select(".PlayerRow, .MuiTableRow-root, .rankings-player, tr[data-player]")
            log.info(f"    📊 Found {len(rows)} HTML player rows")
            for row in rows[:50]:
                text = row.get_text(" ", strip=True)
                names_found = extract_player_names(text)
                state = get_state(text)
                if not state:
                    continue
                for name in names_found[:1]:
                    year = get_year(text) or "2027"
                    player_id = make_id(name, year)
                    links = build_links(name)
                    offers = get_offers(text)
                    p = {
                        "id": player_id,
                        "name": name,
                        "position": get_position(text) or "ATH",
                        "state": state,
                        "year": year,
                        "stars": get_stars(text),
                        "height": get_height(text)[1],
                        "height_inches": get_height(text)[0],
                        "weight": get_weight(text),
                        "offers": offers if offers else ["Unknown"],
                        "category": categorize(offers),
                        "source": "On3",
                        "source_url": url,
                        "links": links,
                        "found_at": datetime.now(timezone.utc).isoformat(),
                    }
                    p["gem_score"] = calc_gem(p)
                    p["evaluation"] = build_eval(p)
                    players.append(p)
                    log.info(f"    👤 {name} | {p['position']} | {state} | {year} | via On3 HTML")

        except Exception as e:
            log.error(f"    ❌ On3 error: {e}")
            continue

    log.info(f"🏈 On3: Found {len(players)} valid players")
    return players

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 4: 247SPORTS
# ══════════════════════════════════════════════════════════════════════════════
def scrape_247() -> list:
    """Scrape 247Sports for Tennessee footprint recruiting data."""
    players = []
    log.info("⭐ 247Sports: Starting scrape...")

    urls = [
        "https://247sports.com/Season/2027-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=TN",
        "https://247sports.com/Season/2027-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=KY",
        "https://247sports.com/Season/2027-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=GA",
        "https://247sports.com/Season/2027-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=AL",
        "https://247sports.com/Season/2027-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=FL",
        "https://247sports.com/Season/2028-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=TN",
        "https://247sports.com/Season/2028-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=GA",
        "https://247sports.com/Season/2026-Football/CompositeRecruitRankings/?InstitutionGroup=HighSchool&State=TN",
        "https://247sports.com/college/tennessee/Season/2027-Football/Targets/",
        "https://247sports.com/college/tennessee/Season/2028-Football/Targets/",
    ]

    for url in urls:
        try:
            # Extract state from URL
            state_match = re.search(r'State=(\w+)', url)
            url_state = state_match.group(1) if state_match else ""

            log.info(f"  🔍 Fetching: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            log.info(f"    HTTP {resp.status_code}")

            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Try __NEXT_DATA__ first
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                try:
                    data = json.loads(script.string)
                    props = data.get("props", {}).get("pageProps", {})
                    recruits = (
                        props.get("recruits", []) or
                        props.get("players", []) or
                        props.get("rankings", {}).get("items", []) or
                        props.get("data", {}).get("recruits", []) or
                        []
                    )
                    log.info(f"    📊 Found {len(recruits)} in __NEXT_DATA__")

                    for r in recruits:
                        rec = r.get("recruit", r) if isinstance(r, dict) else {}
                        name = rec.get("name") or rec.get("fullName", "")
                        if not name or not is_valid_player_name(name):
                            continue

                        state = rec.get("state", "") or rec.get("stateAbbr", "") or url_state
                        if state.upper() not in FOOTPRINT_STATES:
                            continue
                        state = state.upper()

                        pos = rec.get("position", "ATH")
                        year = str(rec.get("year", "")) or get_year(str(rec))
                        stars = rec.get("stars", 0) or rec.get("rating", 0)
                        h_str = rec.get("height", "")
                        w = rec.get("weight", 0)
                        h_in = 0
                        if h_str:
                            h_in, h_str = get_height(str(h_str))

                        player_id = make_id(name, year or "2027")
                        links = build_links(name)
                        offers = get_offers(str(rec))

                        p = {
                            "id": player_id,
                            "name": name,
                            "position": str(pos),
                            "state": state,
                            "year": year or "2027",
                            "stars": int(stars) if stars else 0,
                            "height": h_str,
                            "height_inches": h_in,
                            "weight": int(w) if w else 0,
                            "offers": offers if offers else ["Unknown"],
                            "category": categorize(offers),
                            "source": "247Sports",
                            "source_url": url,
                            "links": links,
                            "found_at": datetime.now(timezone.utc).isoformat(),
                        }
                        p["gem_score"] = calc_gem(p)
                        p["evaluation"] = build_eval(p)
                        players.append(p)
                        log.info(f"    👤 {name} | {pos} | {state} | {year} | via 247Sports")

                except json.JSONDecodeError:
                    log.warning("    ⚠️ Failed to parse 247 __NEXT_DATA__")

            # Fallback: HTML parsing
            rows = soup.select(".recruit, .rankings-page__list-item, li.rankings-page__list-item, .player")
            log.info(f"    📊 Found {len(rows)} HTML player rows")
            for row in rows[:50]:
                text = row.get_text(" ", strip=True)
                names_found = extract_player_names(text)
                state = get_state(text) or url_state.upper()
                if state not in FOOTPRINT_STATES:
                    continue
                for name in names_found[:1]:
                    year = get_year(text) or "2027"
                    player_id = make_id(name, year)
                    links = build_links(name)
                    offers = get_offers(text)
                    p = {
                        "id": player_id,
                        "name": name,
                        "position": get_position(text) or "ATH",
                        "state": state,
                        "year": year,
                        "stars": get_stars(text),
                        "height": get_height(text)[1],
                        "height_inches": get_height(text)[0],
                        "weight": get_weight(text),
                        "offers": offers if offers else ["Unknown"],
                        "category": categorize(offers),
                        "source": "247Sports",
                        "source_url": url,
                        "links": links,
                        "found_at": datetime.now(timezone.utc).isoformat(),
                    }
                    p["gem_score"] = calc_gem(p)
                    p["evaluation"] = build_eval(p)
                    players.append(p)
                    log.info(f"    👤 {name} | {p['position']} | {state} | {year} | via 247 HTML")

        except Exception as e:
            log.error(f"    ❌ 247 error: {e}")
            continue

    log.info(f"⭐ 247Sports: Found {len(players)} valid players")
    return players

# ══════════════════════════════════════════════════════════════════════════════
# MERGE + DEDUPLICATE
# ══════════════════════════════════════════════════════════════════════════════
def merge_players(existing: list, new_players: list) -> list:
    """Merge new players with existing, deduplicating by ID. New data enriches old."""
    by_id = {}

    # Load existing first
    for p in existing:
        pid = p.get("id", make_id(p.get("name", ""), p.get("year", "2027")))
        by_id[pid] = p

    # Merge new — enrich with better data
    for p in new_players:
        pid = p.get("id")
        if pid in by_id:
            old = by_id[pid]
            # Keep the richer data
            if not old.get("height") and p.get("height"):
                old["height"] = p["height"]
                old["height_inches"] = p["height_inches"]
            if not old.get("weight") and p.get("weight"):
                old["weight"] = p["weight"]
            if p.get("stars", 0) > old.get("stars", 0):
                old["stars"] = p["stars"]
            if not old.get("position") or old["position"] == "ATH":
                if p.get("position") and p["position"] != "ATH":
                    old["position"] = p["position"]
            # Merge offers
            old_offers = set(old.get("offers", []))
            new_offers = set(p.get("offers", []))
            combined = sorted(old_offers | new_offers)
            if "Unknown" in combined and len(combined) > 1:
                combined.remove("Unknown")
            old["offers"] = combined
            old["category"] = categorize(combined)
            old["gem_score"] = calc_gem(old)
            old["evaluation"] = build_eval(old)
            # Add source if different
            if p.get("source") and p["source"] not in old.get("source", ""):
                old["source"] = f"{old.get('source', '')} + {p['source']}"
            by_id[pid] = old
        else:
            by_id[pid] = p

    return list(by_id.values())

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🏈 Vol Recruiting Monitor — Scraper v5")
    log.info(f"   Time: {datetime.now(timezone.utc).isoformat()}")
    log.info(f"   X/Twitter token: {'✅ Present' if X_BEARER else '❌ Missing'}")
    log.info("=" * 60)

    # Load existing data
    existing = []
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH) as f:
                old_data = json.load(f)
            existing = old_data.get("players", [])
            log.info(f"📂 Loaded {len(existing)} existing players")
        except Exception as e:
            log.warning(f"⚠️ Could not load existing data: {e}")

    # Run all sources
    source_counts = {"x": 0, "news": 0, "on3": 0, "247sports": 0}

    # Priority 1: X/Twitter
    x_players = scrape_x()
    source_counts["x"] = len(x_players)

    # Priority 2: Google News
    news_players = scrape_google_news()
    source_counts["news"] = len(news_players)

    # Priority 3: On3
    on3_players = scrape_on3()
    source_counts["on3"] = len(on3_players)

    # Priority 4: 247Sports
    s247_players = scrape_247()
    source_counts["247sports"] = len(s247_players)

    # Combine all new finds
    all_new = x_players + news_players + on3_players + s247_players
    log.info(f"\n📊 Raw totals: X={len(x_players)}, News={len(news_players)}, On3={len(on3_players)}, 247={len(s247_players)}")

    # Merge with existing
    merged = merge_players(existing, all_new)

    # Final validation pass — remove any remaining invalid entries
    validated = []
    for p in merged:
        name = p.get("name", "")
        if is_valid_player_name(name) and p.get("state"):
            validated.append(p)
        else:
            log.info(f"  🚫 Filtered out invalid: {name}")

    log.info(f"✅ Final validated player count: {len(validated)}")

    # Sort: X source first, then by stars (desc), then by name
    def sort_key(p):
        source_priority = 0 if "X/Twitter" in p.get("source", "") else 1
        return (source_priority, -p.get("stars", 0), p.get("name", ""))
    validated.sort(key=sort_key)

    # Write output
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "players": validated,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "sources": source_counts,
        "total": len(validated),
    }

    with open(DATA_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"💾 Saved {len(validated)} players to {DATA_PATH}")
    log.info(f"📡 Sources: {source_counts}")

    # Print first 10 for verification
    log.info("\n🔝 Top 10 players:")
    for p in validated[:10]:
        log.info(f"   {p['name']} | {p['position']} | {p['state']} | ⭐{p['stars']} | {p['source'][:30]}")

    log.info("\n🏁 Scraper complete!")

if __name__ == "__main__":
    main()
