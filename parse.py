"""Rule-based RFQ parser: regex + a fuzzy typo pass + an offline city gazetteer.

parse_rfq(text) -> {category, quantity, unit, gsm, micron, location}
"""
import re
from difflib import get_close_matches

import geonamescache

# --------------------------------------------------------------------------
# 1. Normalisation: lowercase, strip digit-group commas, fix typos, word numbers
# --------------------------------------------------------------------------

# Words worth typo-correcting (only words of 5+ letters are fuzzed, cutoff 0.8).
TYPO_VOCAB = [
    "bags", "sacks", "woven", "laminated", "lamination", "jumbo", "pouch", "pouches",
    "carton", "cartons", "corrugated", "boxes", "shrink", "stretch", "films", "capacity",
    "pieces", "cement", "thousand", "micron", "microns", "zipper", "standup", "delivery",
    "hazaar", "quantity", "cardboard", "duplex", "flexible", "packing", "required",
]

MULT = {
    "k": 1e3, "thousand": 1e3, "hundred": 1e2, "sau": 1e2, "million": 1e6, "mn": 1e6,
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
}
MULT_RE = (r"(?:lakhs?|lacs?|laakh|lakh|lkh|lack|crores?|cr|k|thousand|hundred|sau|"
           r"million|mn|ha[zj]+a*r|hzr)")

WORD_NUM = {
    "a": 1, "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4,
    "chaar": 4, "four": 4, "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "six": 6,
    "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10,
    "dus": 10, "ten": 10, "pandrah": 15, "fifteen": 15, "bees": 20, "twenty": 20,
    "pachas": 50, "pachaas": 50, "fifty": 50, "dedh": 1.5, "dhai": 2.5, "dhaai": 2.5,
    "sawa": 1.25, "half": 0.5, "aadha": 0.5, "adha": 0.5,
}


def mult_value(word):
    if not word:
        return 1
    if word.startswith(("lak", "lac", "lkh", "laa")):
        return 1e5
    if word.startswith(("haz", "haj", "hzr")):
        return 1e3
    return MULT[word]


def normalise(text):
    t = text.lower().replace("’", "'")
    t = re.sub(r"(?<=\d),(?=\d)", "", t)                       # 1,50,000 -> 150000
    t = re.sub(r"\bg\.?s\.?m\.?(?![a-z])", "gsm", t)            # g.s.m -> gsm
    t = re.sub(r"(\d)\s*l\s+(?=(?:pcs|pc|pieces|nos|bags|pouches|boxes|cartons|sacks)\b)",
               r"\1 lakh ", t)                                   # 2.5L pcs -> 2.5 lakh pcs
    t = re.sub(r"[a-z]{5,}", lambda m: (get_close_matches(m.group(), TYPO_VOCAB, 1, 0.8)
                                        or [m.group()])[0], t)
    # "do lakh", "dedh lakh", "paanch hazaar" -> digits (only before a multiplier)
    words = "|".join(sorted(WORD_NUM, key=len, reverse=True))
    t = re.sub(rf"\b({words})\s+(?={MULT_RE}\b)", lambda m: f"{WORD_NUM[m.group(1)]} ", t)
    return t


# --------------------------------------------------------------------------
# 2. Category
# --------------------------------------------------------------------------

BAG = r"\b(bags?|sacks?|bori|bora|katt?as?|thail[ae]s?)\b"
FILM = r"\b(films?|wrap|wrapping|stretch|shrink|cling)\b"


def find_category(n):
    has = lambda p: re.search(p, n)
    if has(r"\b(fibcs?|jumbo|bulk\s*bags?|big\s*bags?|tonn?e?\s*bags?|super\s*sacks?)\b"):
        return "fibc"
    if has(r"\bbo+pp?\b|bopp"):
        return "film" if has(FILM) and not has(BAG) else "bopp_bag"
    if has(r"\blaminat") and has(BAG):
        return "bopp_bag"          # "laminated bags" in this trade means BOPP-laminated
    if has(r"\b(woven|cement|ad\s*-?\s*star|adstar|raffia|leno|gunny|sacks?|bori|bora|katt?as?)\b"):
        return "woven_sack"
    if has(r"\b(pouch|pouches|stand\s*-?\s*up|zipper|zip\s*-?\s*lock|ziplock|doy\s*pack|sachets?|spout)"):
        return "pouch"
    if has(r"\b(corrugated|\d+\s*ply|cardboard|shipper|master\s*cartons?)\b"):
        return "corrugated_box"
    if has(r"\b(mono\s*-?\s*cartons?|mono|duplex|folding|fbb|sbs)\b"):
        return "mono_carton"
    if has(FILM):
        return "film"
    if has(r"\b(box|boxes|cartons?|peti)\b"):
        return "corrugated_box"
    if has(BAG):
        return "woven_sack"        # generic pp / hdpe bags
    return None


# --------------------------------------------------------------------------
# 3. Quantity + unit
# --------------------------------------------------------------------------

NUM_RE = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)(?:\s*({MULT_RE})(?![a-z]))?")
RANGE_RE = re.compile(r"\s*(?:-|to)\s*\d+(?:\.\d+)?")
# Numbers followed by these are specs (size, thickness, price, time), never the quantity.
SPEC_AFTER = re.compile(
    r"\s*(?:gsm|g\s*/\s*m2|gm\s*/\s*m2|g\s*/\s*sqm|microns?|mic\b|mcr|mu\b|µ|μ|um\b|gauge|"
    r"mm\b|cm\b|inch|inches|\"|''|ft\b|feet|foot|mtrs?\b|meters?|metres?|m\b|ply|layers?|"
    r"colou?rs?|clr|sided?\b|loops?|panels?|days?|din\b|weeks?|months?|hrs?\b|hours?|%|"
    r"[x×*]\s*\d|denier|mesh|ml\b|ltrs?\b|litres?|liters?|l\b|gms?\b|grams?|g\b|rs\b|inr|₹|/-|"
    r"years?|yrs?|st\b|nd\b|rd\b|th\b|am\b|pm\b)")
# "gsm 65", "size 18": spec word then number. Not when the spec word already has its own
# number ("23 micron 2 MT" -> the 2 is the quantity).
SPEC_BEFORE = re.compile(
    r"(?:(?<!\d)(?<!\d )(?:gsm|microns?|mic|thickness|size|gauge|ply)|\d\s*[x×*]|rs\.?|inr|₹|@|"
    r"price|rate|pin|pincode|pin\s*code|zip|budget|width|length|height|dia)\s*[:\-=]?\s*$")
MT_AFTER = re.compile(r"\s*(?:metric\s*)?(?:tonnes?|tons?|mts?\b|m\.t\.?|tn\b)")
KG_AFTER = re.compile(r"\s*(?:kgs?\b|kilos?\b|kilograms?|kilo\b)")
QUINTAL_AFTER = re.compile(r"\s*(?:quintals?|qtl)\b")
COUNT_AFTER = re.compile(r"\s*(?:pcs|pc\b|pieces?|nos?\b|numbers?\b|units?\b|nags?\b)")
CONTAINER = re.compile(r"\b(bags?|sacks?|bori|bora|katt?as?|box|boxes|cartons?|pouch|pouches|"
                       r"rolls?|fibcs?|sachets?|liners?|thail[ae]s?|peti)\b")
FILL_CONTAINER = re.compile(r"\b(bags?|sacks?|bori|bora|katt?as?|box|boxes|cartons?|pouch|pouches|"
                            r"fibcs?|sachets?|thail[ae]s?|peti)\b")  # not rolls: "500 kg film rolls"
FILL_AFTER = re.compile(r"\b(capacity|cap|packing|pack|filling|fill|load|swl|wala|wale|wali|"
                        r"vala|vale|each|bharne)\b")
FILL_BEFORE = re.compile(r"\b(capacity|cap|swl|load|holding|hold|of|each|filling|fill)\s*[:\-]?\s*$")


def next_words(s, k=3):
    """Up to k words after a number, stopping at the next number or punctuation."""
    return " ".join(re.split(r"[\d,;.()/|]", s, maxsplit=1)[0].split()[:k])


def find_quantity(n, category):
    counts, weights, fills, bares = [], [], [], []
    for m in NUM_RE.finditer(n):
        digits = m.group(1)
        if len(digits.replace(".", "")) >= 10:          # phone numbers
            continue
        before, after = n[:m.start()], n[m.end():]
        after_unit = RANGE_RE.sub("", after, count=1) if RANGE_RE.match(after) else after
        if SPEC_BEFORE.search(before) or SPEC_AFTER.match(after_unit):
            continue
        value = float(digits) * mult_value(m.group(2))
        if MT_AFTER.match(after_unit):
            unit = "mt"
            rest = after_unit[MT_AFTER.match(after_unit).end():]
        elif KG_AFTER.match(after_unit) or QUINTAL_AFTER.match(after_unit):
            unit = "kg"
            if QUINTAL_AFTER.match(after_unit):
                value *= 100
            rest = re.sub(r"^\s*[a-z]+", "", after_unit)
        else:
            if COUNT_AFTER.match(after_unit) or CONTAINER.search(next_words(after_unit, 4)):
                counts.append(value)
            else:
                bares.append((m.group(2) is not None, value))
            continue
        # A weight right before a bag word / "capacity" is the fill weight, not the order.
        is_fill = (FILL_CONTAINER.search(next_words(rest)) or FILL_AFTER.search(next_words(rest))
                   or FILL_BEFORE.search(before))
        (fills if is_fill else weights).append((value, unit))

    to_kg = lambda w: w[0] * (1000 if w[1] == "mt" else 1)
    if counts:
        return counts[0], "pcs"
    if bares and category != "film":
        return max(bares)[1], "pcs"        # prefer numbers with lakh/k/hazaar, then largest
    if weights:
        return max(weights, key=to_kg)
    if bares:
        return max(bares)[1], "kg"         # film sold by weight when no unit given
    # ponytail: "2 ton woven bags" -> order in tonnes; "25 kg bags" alone -> no quantity
    tonnes = [w for w in fills if w[1] == "mt" and category != "fibc"]
    if tonnes:
        return tonnes[0]
    return None, None


# --------------------------------------------------------------------------
# 4. GSM / micron
# --------------------------------------------------------------------------

def find_spec(n, after_pat, before_pat):
    m = (re.search(rf"(\d+(?:\.\d+)?)\s*(?:{after_pat})(?![a-z])", n)
         or re.search(rf"(?:{before_pat})\s*[:\-=]?\s*(\d+(?:\.\d+)?)", n))
    return float(m.group(1)) if m else None


def find_gsm(n):
    v = find_spec(n, r"gsm|g\s*/\s*m2|gm\s*/\s*m2|g\s*/\s*sqm", r"\bgsm")
    return round(v) if v is not None else None


def find_micron(n):
    v = find_spec(n, r"microns?|mic|mcr|mu|µm?|μm?|um", r"\b(?:microns?|mic|thickness)")
    if v is not None:
        return round(v)
    g = re.search(r"(\d+)\s*gauge", n)               # Indian film trade: 100 gauge = 25 micron
    return round(int(g.group(1)) / 4) if g else None


# --------------------------------------------------------------------------
# 5. Location: offline gazetteer (GeoNames cities 15k+, countries) + cue-word fallback
# --------------------------------------------------------------------------

# Words that are also place names somewhere, or that appear in RFQs and must never be a city.
STOP = set("""
a an the and or of for to at in on by with from per pls plz please need needed want required
require requirement urgent urgently quote quotation rate rates price prices best kindly sir ji bhai
send share call contact asap order bulk regular monthly month week supply supplier delivery deliver
dispatch ship location loc site destination near print printed printing plain white colour color
multi brown natural transparent clear virgin recycled food grade export import quality new
bag bags sack sacks box boxes carton cartons pouch pouches film roll rolls wrap jumbo bopp woven
laminated cement star ad kg kgs mt ton tons tonne pcs pieces nos gsm mic micron ply size capacity
hai ka ki ke ko se me mein mai tak chahiye chaiye chahie chahiya liye wala wale wali karo kar do
batao bata bhejo jaldi aur ya bhi hoga hona chahte kitna kya maal saath par pe abhi turant
lakh lac hazaar hazar thousand stretch shrink cling mono duplex corrugated zipper standup stand
hdpe ldpe lldpe pp pet bopp fibc liner sample samples type urgent total approx around about
best good fast quick same next only also just more less this that these those we our us you your
une pen ron bari mandi nagar dam bid sur sita dhar
mobile reading nice split bath most best born deal hope may june july march august sale
aram bada badi bala bali chala dera gola jara kadi kant kim kira lekh mango mesa meta mon naha
pari raja rata sigma tank than tane turk van vala vada wadi wari weir punch pest oral lone gil
gill khana rona bhoja kita mali tura jos lar ton chas hatti basi riva sika
""".split())

STATES = """andhra pradesh|arunachal pradesh|assam|bihar|chhattisgarh|goa|gujarat|haryana|
himachal pradesh|jharkhand|karnataka|kerala|madhya pradesh|maharashtra|manipur|meghalaya|
mizoram|nagaland|odisha|orissa|punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|
uttar pradesh|uttarakhand|west bengal|delhi ncr|ncr|jammu|kashmir""".replace("\n", "")

DELIVERY_CUE_BEFORE = {"to", "at", "in", "deliver", "delivery", "dispatch", "ship", "location",
                       "loc", "site", "destination", "near", "till", "upto", "city"}
DELIVERY_CUE_AFTER = {"tak", "mein", "me", "mai", "delivery", "ke", "ka", "ko", "location", "site"}


def build_gazetteer():
    gc = geonamescache.GeonamesCache()
    gaz = {}
    ascii_name = re.compile(r"^[a-z][a-z .'-]+[a-z]$")

    def add(name, tier):
        key = re.sub(r"\s+", " ", name.lower().strip())
        if ascii_name.match(key) and key not in STOP:
            gaz[key] = min(tier, gaz.get(key, tier))

    for c in gc.get_cities().values():
        if c["countrycode"] == "IN":
            add(c["name"], 1)
            for alt in c.get("alternatenames", []):    # Baroda, Bombay, Gurgaon, Tirupur...
                if len(alt) >= 4:
                    add(alt, 1)
        elif c["population"] >= 300000:
            add(c["name"], 1)
    for c in gc.get_countries().values():
        add(c["name"], 2)                               # "Pune, India" -> Pune
    for alias in ["uae", "u.a.e", "usa", "u.s.a", "uk", "ksa", "us"]:
        gaz[alias] = 2
    for s in STATES.split("|"):
        gaz.setdefault(s.strip(), 3)                    # states only if no city is named
    return gaz


GAZ = build_gazetteer()
WORD_RE = re.compile(r"[A-Za-z][A-Za-z.]*[A-Za-z]|[A-Za-z]")


def find_location(text):
    words = [(m.group().rstrip("."), m.start(), m.end()) for m in WORD_RE.finditer(text)]
    lows = [w[0].lower() for w in words]
    best, best_key = None, None
    i = 0
    while i < len(words):
        for size in (3, 2, 1):
            if i + size > len(words):
                continue
            key = " ".join(lows[i:i + size])
            if key not in GAZ:
                continue
            first = words[i][0]
            # Short names (Una, Mau, US) and lowercase generic words need capitals to count.
            if size == 1 and (key in STOP or (len(key) <= 3 and not first[0].isupper())):
                continue
            span = text[words[i][1]:words[i + size - 1][2]]
            cue = ((i > 0 and lows[i - 1] in DELIVERY_CUE_BEFORE)
                   or (i + size < len(words) and lows[i + size] in DELIVERY_CUE_AFTER))
            rank = (-GAZ[key], bool(cue), i)            # city > country > state, then cue, then last
            if best_key is None or rank >= best_key:
                best, best_key = span, rank
            i += size - 1
            break
        i += 1
    # An explicit delivery phrase wins, even for places not in the gazetteer
    # ("office in Mumbai, deliver Kalamboli" -> Kalamboli).
    m = re.search(r"\b(?:deliver(?:y|ed)?(?:\s+(?:to|at|in))?|dispatch\s+to|ship(?:ping)?\s+to|"
                  r"location|destination|site)\s*[:\-]?\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text)
    if m and m.group(1).lower() not in STOP:
        return m.group(1)
    if best:
        return best
    # Last resort: a capitalised word standing alone as the last comma-separated chunk.
    last = text.strip().rstrip(".!").split(",")[-1].strip()
    if re.fullmatch(r"[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?", last) and last.lower() not in STOP:
        return last
    return None


# --------------------------------------------------------------------------

def parse_rfq(text: str) -> dict:
    n = normalise(text)
    category = find_category(n)
    quantity, unit = find_quantity(n, category)
    if quantity is not None and float(quantity).is_integer():
        quantity = int(quantity)
    return {
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "gsm": find_gsm(n),
        "micron": find_micron(n),
        "location": find_location(text),
    }


if __name__ == "__main__":
    for msg, want in [
        ("bopp bags chahiye 40 hazaar, 65 gsm, Nagpur",
         {"category": "bopp_bag", "quantity": 40000, "unit": "pcs", "gsm": 65, "micron": None,
          "location": "Nagpur"}),
        ("jumbo bag 1000 kg capacity, 500 pcs, Vadodara",
         {"category": "fibc", "quantity": 500, "unit": "pcs", "gsm": None, "micron": None,
          "location": "Vadodara"}),
        ("need quote for 500 kg shrink wrap 25 mic",
         {"category": "film", "quantity": 500, "unit": "kg", "gsm": None, "micron": 25,
          "location": None}),
    ]:
        got = parse_rfq(msg)
        assert got == want, (msg, got)
    print("worked examples OK")
