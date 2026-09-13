# -*- coding: utf-8 -*-
"""Emit the trike goods demo: five member graphs + a workspace.

    python examples/generate_trike_demo.py [output directory]

Deterministic: same input, same bytes. The point of the demo is an ontology
actually in use — declared shapes, typed objects, properties on the objects,
actions that happened *between* two objects and are dated like it, and a
declared actor on every one of them.

The files this writes are committed, so the generator and its output can
disagree — and a demo that no longer comes out of its own generator is a
demo nobody can safely change. `test_the_demo_still_comes_out_of_its_own_
generator` runs this into a temporary directory and diffs.
"""
import os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else HERE
R = random.Random(20250913)

# --------------------------------------------------------------- scalars
def sv(v):
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(sv(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s.startswith("@date:"):
        return s[6:]
    # '?' too: in flow style a leading one is YAML's explicit-key marker, so
    # an unquoted '?order PLACED_BY ?s' parses as a mapping, not a string
    safe = all(c not in s for c in ':#,{}[]"\'?\n') and s.strip() == s and s != ""
    if safe and not s[0].isdigit() and s.lower() not in ("true", "false", "null", "yes", "no", "on", "off"):
        return s
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def key(k):
    return sv(k)

def flow(d):
    return "{" + ", ".join("%s: %s" % (key(k), sv(v)) for k, v in d.items()) + "}"

def triple(t):
    """Short triples stay on one line; the ones carrying a payload get a block
    so the attributes are readable."""
    rest = {k: v for k, v in t.items() if k not in ("s", "p", "o")}
    one = "  - " + flow(t)
    if len(rest) <= 1 and len(one) <= 96:
        return one
    lines = ["  - s: %s" % sv(t["s"]), "    p: %s" % sv(t["p"]), "    o: %s" % sv(t["o"])]
    lines += ["    %s: %s" % (key(k), sv(v)) for k, v in rest.items()]
    return "\n".join(lines)

def write(name, header, preds, nodes, sections):
    buf = [header.rstrip(), ""]
    buf.append("ontology:")
    buf.append("  predicates:")
    for p, d in preds:
        buf.append("    %s: %s" % (p, flow(d)))
    buf.append("")
    buf.append("nodes:")
    for group, items in nodes:
        if group:
            buf.append("  # " + group)
        for n, meta in items:
            buf.append("  %s: %s" % (key(n), flow(meta)))
    buf.append("")
    buf.append("triples:")
    total = 0
    for comment, ts in sections:
        buf.append("")
        for line in comment.strip("\n").split("\n"):
            buf.append("  # " + line if line else "  #")
        for t in ts:
            buf.append(triple(t))
        total += len(ts)
    path = os.path.join(OUT, name)
    open(path, "w").write("\n".join(buf).rstrip() + "\n")
    ev = sum(1 for _, ts in sections for t in ts if "at" in t)
    print("%-28s %4d triples  %3d events  %3d nodes" % (name, total, ev,
          sum(len(i) for _, i in nodes)))
    return total, ev

def D(d):
    return "@date:" + d

def day(year, month, dom):
    return D("%04d-%02d-%02d" % (year, month, dom))

# ------------------------------------------------------------------ data
REGIONS = ["Riverside", "Northfield", "Harbour District", "Old Quarter"]
PLANS = ["Trike Free", "Trike Plus", "Trike Pantry Club"]
CATEGORIES = ["Kitchen", "Tableware", "Pantry", "Linens", "Cleaning", "Stationery"]
SUPPLIERS = [
    ("Kettleworks Ltd", "Kitchen"),
    ("Basalt Cookware", "Kitchen"),
    ("Nomi Ceramics", "Tableware"),
    ("Verdant Farms", "Pantry"),
    ("Arbor Textiles", "Linens"),
    ("Pinefield Paper", "Stationery"),
]
PRODUCTS = [
    # (name, category, supplier, price, stock)
    ("Copper Kettle 1.5L", "Kitchen", "Kettleworks Ltd", 8400, 62),
    ("Cast Iron Skillet 26cm", "Kitchen", "Basalt Cookware", 6900, 48),
    ("Bamboo Cutting Board", "Kitchen", "Basalt Cookware", 3200, 140),
    ("Enamel Stockpot 6L", "Kitchen", "Kettleworks Ltd", 11800, 26),
    ("Silicone Spatula Set", "Kitchen", "Basalt Cookware", 1900, 210),
    ("Pour-Over Dripper", "Kitchen", "Nomi Ceramics", 2800, 95),
    ("Stoneware Dinner Plate", "Tableware", "Nomi Ceramics", 2400, 320),
    ("Matte Mug 350ml", "Tableware", "Nomi Ceramics", 1600, 410),
    ("Glass Tumbler 300ml", "Tableware", "Nomi Ceramics", 1100, 380),
    ("Walnut Serving Tray", "Tableware", "Arbor Textiles", 5600, 44),
    ("Ceramic Bowl 18cm", "Tableware", "Nomi Ceramics", 2100, 260),
    ("Linen Napkin Set", "Tableware", "Arbor Textiles", 3400, 130),
    ("Single-Origin Coffee 250g", "Pantry", "Verdant Farms", 1800, 540),
    ("Sencha Loose Leaf 100g", "Pantry", "Verdant Farms", 1500, 300),
    ("Cold-Pressed Olive Oil 500ml", "Pantry", "Verdant Farms", 2600, 180),
    ("Sea Salt Flakes 120g", "Pantry", "Verdant Farms", 900, 420),
    ("Buckwheat Soba 300g", "Pantry", "Verdant Farms", 700, 610),
    ("Wildflower Honey 340g", "Pantry", "Verdant Farms", 2200, 150),
    ("Waffle Bath Towel", "Linens", "Arbor Textiles", 3900, 170),
    ("Linen Duvet Cover", "Linens", "Arbor Textiles", 14800, 34),
    ("Cotton Throw Blanket", "Linens", "Arbor Textiles", 7600, 58),
    ("Percale Pillowcase Pair", "Linens", "Arbor Textiles", 4200, 120),
    ("Coconut Dish Soap 500ml", "Cleaning", "Verdant Farms", 850, 480),
    ("Wool Dryer Balls", "Cleaning", "Arbor Textiles", 1400, 220),
    ("Bamboo Dish Brush", "Cleaning", "Basalt Cookware", 600, 350),
    ("Citrus Surface Spray", "Cleaning", "Verdant Farms", 1000, 290),
    ("Recycled Notebook A5", "Stationery", "Pinefield Paper", 1200, 400),
    ("Fineliner Pen Set", "Stationery", "Pinefield Paper", 1700, 240),
    ("Kraft Gift Wrap Roll", "Stationery", "Pinefield Paper", 800, 310),
    ("Desk Blotter Pad", "Stationery", "Pinefield Paper", 2900, 88),
    ("Nesting Mixing Bowls", "Kitchen", "Basalt Cookware", 4300, 76),
    ("Cedar Spice Rack", "Kitchen", "Arbor Textiles", 5100, 52),
    ("Ash Chopstick Pair", "Tableware", "Arbor Textiles", 900, 290),
    ("Speckled Side Plate", "Tableware", "Nomi Ceramics", 1800, 340),
    ("Miso Paste 400g", "Pantry", "Verdant Farms", 1300, 260),
    ("Smoked Paprika 60g", "Pantry", "Verdant Farms", 750, 330),
    ("Linen Tea Towel Set", "Linens", "Arbor Textiles", 2700, 190),
    ("Quilted Bed Runner", "Linens", "Arbor Textiles", 6800, 41),
    ("Refill Hand Wash 1L", "Cleaning", "Verdant Farms", 1100, 275),
    ("Linen-Bound Planner", "Stationery", "Pinefield Paper", 3600, 112),
]
PNAMES = [p[0] for p in PRODUCTS]
PBY = {p[0]: p for p in PRODUCTS}

CUSTOMERS = ["TC-%04d" % (1001 + i) for i in range(48)]
ORDERS = ["ORD-25%03d" % (101 + i) for i in range(84)]

WAREHOUSES = [
    ("Riverside DC", "Riverside", 11000),
    ("Northfield DC", "Northfield", 9000),
    ("Harbour Micro-Hub", "Harbour District", 2200),
    ("Old Quarter Returns", "Old Quarter", 1400),
]
CARRIERS = ["Swiftline", "Harbour Post", "Northfield Freight"]
TEAMS = ["commerce-platform", "fulfilment-ops", "catalog-merch", "customer-care", "data-platform"]
PEOPLE = [
    "Ada Marlowe", "Nils Brandt", "Rune Halvorsen", "Petra Oyelaran",
    "Ines Falk", "Tomas Vidal", "Saoirse Quinn", "Kofi Mensah",
    "Lena Ostrom", "Hugo Peralta", "Mira Lindqvist", "Osei Duah",
    "Freya Nakagawa", "Dario Bellini", "Nadia Sorensen", "Emil Vasquez",
]
SYSTEMS = [
    ("checkout-api", "commerce-platform", "python"),
    ("inventory-service", "commerce-platform", "go"),
    ("order-router", "fulfilment-ops", "go"),
    ("pricing-engine", "catalog-merch", "python"),
    ("wms-core", "fulfilment-ops", "java"),
    ("returns-portal", "customer-care", "typescript"),
    ("search-index", "catalog-merch", "rust"),
]
INCIDENTS = [
    ("INC-2025-01", "sev2", "checkout 5xx spike during the spring sale"),
    ("INC-2025-02", "sev3", "inventory counts drifted after a partial restock feed"),
    ("INC-2025-03", "sev1", "order-router dropped Harbour District dispatches"),
    ("INC-2025-04", "sev3", "pricing-engine applied a stale FX rate"),
    ("INC-2025-05", "sev2", "wms-core pick lists printed out of order"),
    ("INC-2025-06", "sev3", "returns-portal uploads timed out over 5MB"),
    ("INC-2025-07", "sev2", "search-index missed newly listed products for 9 hours"),
    ("INC-2025-08", "sev3", "duplicate confirmation emails on retried payments"),
    ("INC-2025-09", "sev1", "Riverside DC conveyor halt stopped outbound scans"),
    ("INC-2025-10", "sev2", "checkout-api rate limit tripped by a crawler"),
    ("INC-2025-11", "sev3", "inventory-service leaked connections under retry storms"),
    ("INC-2025-12", "sev2", "Northfield Freight label API changed without notice"),
]

# ------------------------------------------------- derived, deterministic
person_team = {p: TEAMS[i % 5] for i, p in enumerate(PEOPLE)}
CAT_MERCH = [p for p in PEOPLE if person_team[p] == "catalog-merch"]

cust_region = {c: REGIONS[i % len(REGIONS)] for i, c in enumerate(CUSTOMERS)}
# everybody joined before the order book opens in 2025, because an order
# placed by an account that does not exist yet is not a thing that can happen
cust_since = {c: "20%02d-%02d-%02d" % (23 + (i // 7) % 2, 1 + (i * 5) % 12, 1 + (i * 7) % 28)
              for i, c in enumerate(CUSTOMERS)}
cust_tier = {c: ["standard", "standard", "plus", "standard", "plus", "gold"][i % 6]
             for i, c in enumerate(CUSTOMERS)}

order_of = {}
order_date = {}
order_lines = {}
for i, o in enumerate(ORDERS):
    # gcd(7, 48) == 1, so orders 0..47 land on 48 distinct customers and
    # the rest are somebody's second order: no customer is a bare map pin
    order_of[o] = CUSTOMERS[(i * 7) % len(CUSTOMERS)]
    order_date[o] = (2025, min(2 + i // 14, 8), 1 + (i * 3) % 27)
    order_lines[o] = [PNAMES[(i * 11) % len(PNAMES)]] + (
        [PNAMES[(i * 23 + 5) % len(PNAMES)]] if i % 5 == 0 else [])

# the last day each product left the shelf, so nothing is retired while it
# is still selling and nothing is sold after it is retired
last_sold = {}
for o in ORDERS:
    for n in order_lines[o]:
        if order_date[o] > last_sold.get(n, (0, 0, 0)):
            last_sold[n] = order_date[o]


def dstr(t):
    return "%04d-%02d-%02d" % t

def plus(t, days):
    y, m, d = t
    d += days
    while d > 28:
        d -= 28
        m += 1
    if m > 12:
        m -= 12
        y += 1
    return (y, m, d)

# ================================================================ catalog
preds_catalog = [
    ("SUPPLIES", {"description": "supplier -> product it makes for us", "domain": "supplier", "range": "product"}),
    ("IN_CATEGORY", {"description": "product -> category it is merchandised under", "domain": "product", "range": "category"}),
    ("BUNDLED_WITH", {"description": "product -> product sold alongside it", "domain": "product", "range": "product"}),
    ("SUBSTITUTE_FOR", {"description": "product -> product it can stand in for", "domain": "product", "range": "product"}),
    ("CHANGED", {"description": "price change -> the product it repriced", "domain": "price-change", "range": "product", "by": "system"}),
    ("APPROVED_BY", {"description": "price change -> the person who signed it off", "domain": "price-change", "range": "person"}),
    ("RESTOCKED_FROM", {"description": "product -> supplier the stock came in from", "domain": "product", "range": "supplier", "by": "team"}),
    ("RETIRED", {"description": "retirement -> the product taken off the shelf", "domain": "retirement", "range": "product", "by": "team"}),
    ("DECIDED_BY", {"description": "retirement -> the person who called it", "domain": "retirement", "range": "person"}),
    ("REPLACED_BY", {"description": "retired product -> the product that took over", "domain": "product", "range": "product", "requires": "RETIRED", "by": "team"}),
]

REPRICE_WHY = [
    "supplier raised the unit cost",
    "clearing the last of the spring run",
    "matched a competitor's shelf price",
    "freight surcharge passed through",
    "category margin review",
    "promotional price for the pantry club",
    "packaging changed and the cost with it",
    "FX move on an imported line",
    "volume discount renegotiated",
    "end-of-season markdown",
    "corrected a mis-keyed launch price",
    "cost base moved with the new supply contract",
]

# A price change used to be a sentence hanging off the product. It has a
# before, an after, a reason and an approver, so it is an object: it gets an
# id, its properties go on the node, and it links to the things it touched.
reprice = []
for i in range(12):
    name = PNAMES[(i * 3) % len(PNAMES)]
    base = PBY[name][3]
    after = int(base * (1.08 if i % 3 else 0.9) // 10 * 10)
    reprice.append(("PC-%04d" % (1 + i), name, base, after, REPRICE_WHY[i],
                    plus((2025, 1, 12), i * 17)))
reprice_after = {n: a for _, n, _, a, _, _ in reprice}

restock = []
for i in range(6):
    name = PNAMES[(i * 4 + 1) % len(PNAMES)]
    if any(name == r[0] for r in restock):
        name = PNAMES[(i * 5 + 2) % len(PNAMES)]
    stock = PBY[name][4]
    qty = 40 + i * 15
    restock.append((name, stock - qty, stock, qty, plus((2025, 2, 3), i * 19)))
restock_after = {n: a for n, _, a, _, _ in restock}

retired = [PNAMES[4], PNAMES[17], PNAMES[25], PNAMES[33]]
successor = {PNAMES[4]: PNAMES[2], PNAMES[17]: PNAMES[12],
             PNAMES[25]: PNAMES[22], PNAMES[33]: PNAMES[6]}
RETIRE_WHY = ["supplier stopped the line", "margin below the category floor",
              "replaced by a cheaper equivalent",
              "moved to the supplier's own direct channel"]
retire = [("RET-%04d" % (1 + i), n, RETIRE_WHY[i],
           plus(max(last_sold.get(n, (2025, 5, 6)), (2025, 5, 6)), 9 + i * 9))
          for i, n in enumerate(retired)]
retire_date = {n: d for r, n, why, d in retire}

cat_nodes = [
    ("suppliers — who we buy from", [
        (s, {"type": "supplier", "makes": c.lower(), "url": "https://%s.example" % s.split()[0].lower(),
             "terms": "net-30"}) for s, c in SUPPLIERS]),
    ("categories — how the shop is merchandised", [
        (c, {"type": "category", "aisle": i + 1}) for i, c in enumerate(CATEGORIES)]),
    ("products — price and stock are properties, and the actions below are\n  # what moved them",
     [(n, {"type": "product", "sku": "TG-%03d" % (100 + i),
           "price_jpy": reprice_after.get(n, pr),
           "stock": restock_after.get(n, st),
           "category": cat,
           "listed": n not in retired}) for i, (n, cat, sup, pr, st) in enumerate(PRODUCTS)]),
    ("price changes and retirements. These used to be a sentence dangling off\n  # the product. A price change has a before, an after, a reason and\n  # somebody who signed it off — that is an object, so it gets an id, its\n  # own properties, and links to the product it moved and the person who\n  # approved it. Ask the graph state('PC-0007') and it answers 'applied'.",
     [(pc, {"type": "price-change", "price_before": b, "price_after": a,
            "reason": why}) for pc, n, b, a, why, d in reprice]
     + [(r, {"type": "retirement", "reason": why}) for r, n, why, d in retire]),
    ("the people who sign those off — the same person nodes the org graph\n  # puts on a team, so the approval is not a free-text initial",
     [(p, {"type": "person", "team": "catalog-merch"}) for p in CAT_MERCH]),
]

ts_supplies = [{"s": sup, "p": "SUPPLIES", "o": n} for n, cat, sup, pr, st in PRODUCTS]
ts_incat = [{"s": n, "p": "IN_CATEGORY", "o": cat} for n, cat, sup, pr, st in PRODUCTS]

ts_bundle = [{"s": PNAMES[i], "p": "BUNDLED_WITH", "o": PNAMES[(i + 8) % 40]} for i in range(2)]
ts_sub = [{"s": PNAMES[i + 10], "p": "SUBSTITUTE_FOR", "o": PNAMES[(i + 23) % 40]} for i in range(2)]
ts_change = [{"s": pc, "p": "CHANGED", "o": n, "at": D(dstr(d)),
              "by": "pricing-engine", "state": "applied"}
             for pc, n, b, a, why, d in reprice]
ts_approve = [{"s": pc, "p": "APPROVED_BY", "o": CAT_MERCH[i % len(CAT_MERCH)]}
              for i, (pc, n, b, a, why, d) in enumerate(reprice)]
ts_restock = [{"s": n, "p": "RESTOCKED_FROM", "o": PBY[n][2],
               "at": D(dstr(d)), "by": "fulfilment-ops", "state": "in-stock",
               "qty": q, "stock_before": b, "stock_after": a}
              for n, b, a, q, d in restock]
ts_retired = [{"s": r, "p": "RETIRED", "o": n, "at": D(dstr(d)),
               "by": "catalog-merch", "state": "executed"}
              for r, n, why, d in retire]
ts_decided = [{"s": r, "p": "DECIDED_BY", "o": CAT_MERCH[(i + 1) % len(CAT_MERCH)]}
              for i, (r, n, why, d) in enumerate(retire)]
ts_repl = [{"s": n, "p": "REPLACED_BY", "o": successor[n],
            "at": D(dstr(plus(retire_date[n], 14))), "by": "catalog-merch",
            "state": "migrated"} for i, n in enumerate(retired)]

HDR_CAT = """# trike goods — catalog
#
# trike goods is a fictional homeware and pantry retailer. This graph is the
# part of its ontology that answers "what do we sell, who makes it, and what
# has happened to it" — one of five member graphs; the workspace
# (trike_workspace.yaml) unions them.
#
# Every predicate below is *declared*, not described: `domain` is the node
# type allowed as the subject and `range` the type allowed as the object, and
# writing an edge between the wrong two types is refused rather than stored.
#
# A product carries properties (price_jpy, stock, sku). An action is what
# moved them, and the node's property is the value the newest action left
# behind — the number on the object and the event that produced it are the
# same fact, not two.
#
# Some actions stay small: RESTOCKED_FROM is one dated line from a product to
# the supplier the stock came in from, carrying stock_before/stock_after.
# Others outgrow that. A price change has a before, an after, a reason and a
# person who signed it off, and a thing with properties and relationships of
# its own is an object — so PC-0001..PC-0012 are nodes here, with CHANGED
# pointing at the product they moved and APPROVED_BY at the person. Same for
# the retirements. Nothing in this file is a floating sentence."""

write("trike_catalog.yaml", HDR_CAT, preds_catalog, cat_nodes, [
    ("who supplies what", ts_supplies),
    ("how it is merchandised", ts_incat),
    ("merchandising relations — plain links, no date: nothing happened,\nthis is just how the shelf is arranged", ts_bundle + ts_sub),
    ("a price change, promoted to an object. The dated link moves the\nproduct; the undated one records who approved it. The before and after\nlive on the PC node, where anything else can point at them too.", ts_change + ts_approve),
    ("stock arriving is still small enough to be one dated line", ts_restock),
    ("end of life — the retirement object, who called it, and the line from\nthe retired product to the one that took over", ts_retired + ts_decided + ts_repl),
])

# =============================================================== commerce
preds_commerce = [
    ("LIVES_IN", {"description": "customer -> delivery region", "domain": "customer", "range": "region"}),
    ("SUBSCRIBED_TO", {"description": "customer -> membership plan they signed up for", "domain": "customer", "range": "plan", "by": "system"}),
    ("PLACED_BY", {"description": "order -> the customer who placed it", "domain": "order", "range": "customer", "by": "system"}),
    ("CONTAINS", {"description": "order -> product on one of its lines", "domain": "order", "range": "product"}),
    ("CANCELLED_BY", {"description": "order -> the customer who called it off", "domain": "order", "range": "customer", "requires": "PLACED_BY", "by": "team"}),
    # A verified purchase, said as a condition rather than as a convention:
    # the order in the middle is named by neither end of the review, so no
    # single-edge check can reach it. ?s and ?o are the review's own two ends.
    ("REVIEWED", {"description": "customer -> product they rated", "domain": "customer", "range": "product",
                  "requires": ["?order PLACED_BY ?s", "?order CONTAINS ?o"]}),
]

cancelled = ORDERS[-6:]
ts_lives = [{"s": c, "p": "LIVES_IN", "o": cust_region[c]} for c in CUSTOMERS]
ts_plan = [{"s": c, "p": "SUBSCRIBED_TO", "o": PLANS[i % 3],
            "at": D(cust_since[c]), "by": "checkout-api",
            "state": ["free", "plus", "pantry-club"][i % 3]}
           for i, c in enumerate(CUSTOMERS[::4])]
reprice_on = {n: d for _, n, b, a, why, d in reprice}


def price_on(n, day):
    """What the thing cost that day: a repricing before it moved the price."""
    pc = reprice_on.get(n)
    return reprice_after[n] if pc and day >= pc else PBY[n][3]


ts_placed = []
for i, o in enumerate(ORDERS):
    tot = sum(price_on(p, order_date[o]) for p in order_lines[o])
    ts_placed.append({"s": o, "p": "PLACED_BY", "o": order_of[o],
                      "at": D(dstr(order_date[o])), "by": "checkout-api",
                      "state": "paid", "total_jpy": tot, "lines": len(order_lines[o])})
ts_contains = [{"s": o, "p": "CONTAINS", "o": p, "qty": 1 + (j % 2)}
               for o in ORDERS for j, p in enumerate(order_lines[o])]
ts_cancel = [{"s": o, "p": "CANCELLED_BY", "o": order_of[o],
              "at": D(dstr(plus(order_date[o], 2))), "by": "customer-care",
              "state": "refunded",
              "reason": ["changed their mind", "found it cheaper elsewhere",
                         "duplicate order", "delivery window too late",
                         "wrong size", "payment disputed"][i]}
             for i, o in enumerate(cancelled)]
# an event does not have to leave a state behind: a review happened on a day
# and carries its rating, but it does not move the customer anywhere
# a review is somebody saying what they made of a thing they bought, so it
# hangs off a real order: the customer who placed it, a product that was on
# it, on a day after it would have arrived
ts_review = [{"s": order_of[o], "p": "REVIEWED", "o": order_lines[o][0],
              "at": D(dstr(plus(order_date[o], 9 + (i % 4) * 3))),
              "rating": [5, 4, 5, 3, 4, 2][i % 6]}
             for i, o in enumerate(ORDERS[1:20:2])]

com_nodes = [
    ("customers — an account, its region and how long it has been with us", [
        (c, {"type": "customer", "region": cust_region[c], "since": cust_since[c],
             "tier": cust_tier[c]}) for c in CUSTOMERS]),
    ("regions and plans", [(r, {"type": "region", "kind": "delivery zone"}) for r in REGIONS]
     + [(p, {"type": "plan", "fee_jpy": [0, 480, 980][i]}) for i, p in enumerate(PLANS)]),
    ("orders", [(o, {"type": "order", "channel": "web" if i % 3 else "app",
                     "placed": dstr(order_date[o])}) for i, o in enumerate(ORDERS)]),
    ("products appear here too — same names as in the catalog graph, so the\n  # workspace joins the two islands instead of leaving them as silos",
     [(n, {"type": "product", "sku": "TG-%03d" % (100 + i)}) for i, (n, c, s, pr, st) in enumerate(PRODUCTS)]),
]

HDR_COM = """# trike goods — commerce
#
# The customer side of the ontology: who bought what, when, and where it
# goes. This is the slide's shape — a customer object, a product object, and
# an action that runs on the line between them carrying its own date and the
# state it left behind.
#
# The order is the subject of PLACED_BY rather than the customer, because an
# event moves the state of whatever it hangs off, and it is the *order* that
# goes paid -> dispatched -> delivered. Ask the graph `state('ORD-25101')`
# and you get 'delivered' — assembled from events in two different member
# graphs, not from a status column somebody has to remember to update."""

write("trike_commerce.yaml", HDR_COM, preds_commerce, com_nodes, [
    ("where a customer takes delivery. No date: this is how things stand,\nnot something that happened.", ts_lives),
    ("signing up for a plan is something that happened on a day, so it is\ndated, and it leaves the customer in a state", ts_plan),
    ("the order itself — order -> customer, dated, with the state it left the\norder in. This is the action layer: an event between two objects.", ts_placed),
    ("what was on the order", ts_contains),
    ("actions taken after the fact", ts_cancel + ts_review),
])

# ============================================================= fulfilment
preds_ful = [
    ("STOCKED_AT", {"description": "product -> warehouse holding it", "domain": "product", "range": "warehouse"}),
    ("SERVES", {"description": "warehouse -> region it delivers into", "domain": "warehouse", "range": "region"}),
    ("SHIPPED_FROM", {"description": "order -> warehouse it went out of", "domain": "order", "range": "warehouse", "requires": "PLACED_BY", "by": "system"}),
    ("CARRIED_BY", {"description": "order -> carrier assigned to it", "domain": "order", "range": "carrier"}),
    ("DELIVERED_TO", {"description": "order -> customer who received it", "domain": "order", "range": "customer", "requires": "SHIPPED_FROM", "by": "carrier"}),
    ("RETURNED_TO", {"description": "order -> warehouse that took it back", "domain": "order", "range": "warehouse", "requires": "DELIVERED_TO", "by": "team"}),
]

WNAMES = [w[0] for w in WAREHOUSES]
ts_stocked = [{"s": n, "p": "STOCKED_AT", "o": WNAMES[i % 4],
               "bin": "%s-%02d" % ("ABCD"[i % 4], i + 1)}
              for i, (n, c, s, pr, st) in enumerate(PRODUCTS) if i % 5 < 1]
ts_serves = [{"s": WNAMES[0], "p": "SERVES", "o": REGIONS[0]},
             {"s": WNAMES[0], "p": "SERVES", "o": REGIONS[3]},
             {"s": WNAMES[1], "p": "SERVES", "o": REGIONS[1]},
             {"s": WNAMES[1], "p": "SERVES", "o": REGIONS[2]},
             {"s": WNAMES[2], "p": "SERVES", "o": REGIONS[2]},
             {"s": WNAMES[3], "p": "SERVES", "o": REGIONS[3]}]
shipped = ORDERS[:28]
ts_ship = [{"s": o, "p": "SHIPPED_FROM", "o": WNAMES[i % 3],
            "at": D(dstr(plus(order_date[o], 1))), "by": "wms-core",
            "state": "dispatched", "wave": "wave-%d" % (1 + i % 4)}
           for i, o in enumerate(shipped)]
ts_carry = [{"s": o, "p": "CARRIED_BY", "o": CARRIERS[i % 3],
             "tracking": "SL%08d" % (72100 + i * 13)} for i, o in enumerate(ORDERS[:10])]
ts_deliv = [{"s": o, "p": "DELIVERED_TO", "o": order_of[o],
             "at": D(dstr(plus(order_date[o], 4))), "by": CARRIERS[i % 3],
             "state": "delivered"} for i, o in enumerate(ORDERS[:20])]
ts_ret = [{"s": ORDERS[i], "p": "RETURNED_TO", "o": WNAMES[3],
           "at": D(dstr(plus(order_date[ORDERS[i]], 11))), "by": "customer-care",
           "state": "refunded", "reason": r}
          for i, r in [(2, "arrived chipped"), (5, "wrong colourway"),
                       (9, "no longer needed"), (14, "duplicate of ORD-25112"),
                       (17, "arrived after the window")]]

ful_nodes = [
    ("warehouses and carriers", [
        (w, {"type": "warehouse", "region": r, "pallets": cap}) for w, r, cap in WAREHOUSES]
     + [(c, {"type": "carrier", "cutoff": ["17:00", "15:30", "19:00"][i]}) for i, c in enumerate(CARRIERS)]),
    ("regions, shared with the commerce graph", [
        (r, {"type": "region", "kind": "delivery zone"}) for r in REGIONS]),
    ("products and the orders that move them — the same nodes the other two\n  # graphs use, which is what makes the workspace a union and not a pile",
     [(n, {"type": "product", "sku": "TG-%03d" % (100 + i)}) for i, (n, c, s, pr, st) in enumerate(PRODUCTS)]
     + [(o, {"type": "order", "placed": dstr(order_date[o])}) for o in shipped]
     + [(c, {"type": "customer", "region": cust_region[c]}) for c in sorted({order_of[o] for o in ORDERS[:20]})]),
]

HDR_FUL = """# trike goods — fulfilment
#
# What physically happens to an order after checkout. Almost every line in
# here is an action with a date on it, because that is what fulfilment is:
# SHIPPED_FROM, DELIVERED_TO and RETURNED_TO each run between two objects
# and carry the state they left the order in.
#
# The two undated predicates are the ones that are not events: where a
# product is kept, and which region a warehouse covers."""

write("trike_fulfilment.yaml", HDR_FUL, preds_ful, ful_nodes, [
    ("standing arrangements — no date, because nothing happened", ts_stocked + ts_serves),
    ("the order leaves the building", ts_ship),
    ("who is carrying it (an assignment, not an event)", ts_carry),
    ("and what became of it", ts_deliv + ts_ret),
])

# ==================================================================== org
preds_org = [
    ("MEMBER_OF", {"description": "person -> team they belong to", "domain": "person", "range": "team"}),
    ("LEADS", {"description": "person -> team they are accountable for", "domain": "person", "range": "team"}),
    ("OPERATES", {"description": "team -> system it runs", "domain": "team", "range": "system"}),
    ("RUNS", {"description": "team -> warehouse it staffs", "domain": "team", "range": "warehouse"}),
    ("OWNS_CATEGORY", {"description": "team -> merchandising category it owns", "domain": "team", "range": "category"}),
    ("SUPPORTS", {"description": "team -> region it covers", "domain": "team", "range": "region"}),
    ("ON_CALL_FOR", {"description": "person -> system they took the pager for", "domain": "person", "range": "system"}),
    ("HANDED_OVER_TO", {"description": "person -> person they passed the pager to", "domain": "person", "range": "person"}),
]

ts_member = [{"s": p, "p": "MEMBER_OF", "o": person_team[p],
              "since": "20%02d-%02d-01" % (22 + i % 4, 1 + (i * 3) % 12)} for i, p in enumerate(PEOPLE)]
ts_leads = [{"s": PEOPLE[i], "p": "LEADS", "o": TEAMS[i]} for i in range(5)]
ts_op = [{"s": team, "p": "OPERATES", "o": sys_} for sys_, team, lang in SYSTEMS]
ts_runs = [{"s": ["fulfilment-ops", "fulfilment-ops", "fulfilment-ops", "customer-care"][i],
            "p": "RUNS", "o": WNAMES[i]} for i in range(4)]
ts_owncat = [{"s": "catalog-merch", "p": "OWNS_CATEGORY", "o": c} for c in CATEGORIES]
ts_support = [{"s": TEAMS[i % 5], "p": "SUPPORTS", "o": REGIONS[i % 4]} for i in range(6)]
ts_oncall = [{"s": PEOPLE[(i * 3) % 16], "p": "ON_CALL_FOR", "o": SYSTEMS[i % 7][0],
              "at": D(dstr(plus((2025, 1, 6), i * 21))), "state": "on-call",
              "rotation": "week-%02d" % (2 + i * 3)} for i in range(8)]
ts_hand = [{"s": PEOPLE[(i * 3) % 16], "p": "HANDED_OVER_TO", "o": PEOPLE[(i * 3 + 3) % 16],
            "at": D(dstr(plus((2025, 1, 13), i * 21))), "state": "handed-over",
            "note": "pager for %s" % SYSTEMS[i % 7][0]} for i in range(6)]

org_nodes = [
    ("teams", [(t, {"type": "team", "headcount": [4, 5, 3, 2, 2][i]}) for i, t in enumerate(TEAMS)]),
    ("people", [(p, {"type": "person", "team": person_team[p],
                     "role": "lead" if i < 5 else "engineer" if i % 2 else "operator"})
                for i, p in enumerate(PEOPLE)]),
    ("the systems those teams run", [
        (s, {"type": "system", "language": lang, "owner": t}) for s, t, lang in SYSTEMS]),
    ("warehouses, categories and regions — shared with the other graphs", [
        (w, {"type": "warehouse", "region": r}) for w, r, cap in WAREHOUSES]
     + [(c, {"type": "category", "aisle": i + 1}) for i, c in enumerate(CATEGORIES)]
     + [(r, {"type": "region", "kind": "delivery zone"}) for r in REGIONS]),
]

HDR_ORG = """# trike goods — org
#
# Who is accountable for what. Most of this is structure rather than
# history, which is the point of keeping it next to the other graphs: a
# question like "who do I page about pricing-engine" is answered by walking
# from the system to the team to the person on call — three hops across two
# member graphs, not a wiki page somebody forgot to update.
#
# MEMBER_OF carries `since` as a plain property, so it is a fact about how
# things stand. ON_CALL_FOR and HANDED_OVER_TO carry `at`, so they are
# events: the pager actually moved, on a day, from someone to someone."""

write("trike_org.yaml", HDR_ORG, preds_org, org_nodes, [
    ("the org chart", ts_member + ts_leads),
    ("what each team is accountable for", ts_op + ts_runs + ts_owncat + ts_support),
    ("the pager — an action between two people, dated like one", ts_oncall + ts_hand),
])

# ============================================================== incidents
preds_inc = [
    ("RAISED_BY", {"description": "incident -> person who opened it", "domain": "incident", "range": "person"}),
    ("AFFECTED", {"description": "incident -> system it is about", "domain": "incident", "range": "system"}),
    ("HELD_UP_BY", {"description": "order -> incident that stalled it", "domain": "order", "range": "incident", "requires": "PLACED_BY"}),
    ("MITIGATED", {"description": "mitigation -> the incident it stopped", "domain": "mitigation", "range": "incident", "requires": "RAISED_BY", "by": "person"}),
    ("RESOLVED_BY", {"description": "incident -> person who closed it", "domain": "incident", "range": "person", "requires": "RAISED_BY"}),
    ("DISRUPTED", {"description": "incident -> warehouse it degraded", "domain": "incident", "range": "warehouse"}),
]

inc_ids = [i[0] for i in INCIDENTS]
inc_open = {inc_ids[i]: plus((2025, 1, 20), i * 19) for i in range(12)}
inc_sys = {inc_ids[i]: SYSTEMS[i % 7][0] for i in range(12)}
ts_raised = [{"s": inc_ids[i], "p": "RAISED_BY", "o": PEOPLE[(i * 5) % 16],
              "at": D(dstr(inc_open[inc_ids[i]])), "state": "open",
              "severity": INCIDENTS[i][1]} for i in range(12)]
ts_aff = [{"s": inc_ids[i], "p": "AFFECTED", "o": inc_sys[inc_ids[i]],
           "blast_radius": ["checkout", "stock", "dispatch", "price", "picking",
                            "returns", "search"][i % 7]} for i in range(6)]
# an order that was stalled: the event hangs off the order, because the order
# is the thing that stopped moving
held, used = [], set()
for i in range(12):
    if len(held) == 5:
        break
    inc = inc_ids[i]
    pool = [o for o in ORDERS[-14:] if o not in used]
    early = [o for o in pool if order_date[o] <= inc_open[inc]]
    o = (early or pool)[-1]
    used.add(o)
    held.append((o, inc))
ts_held = [{"s": o, "p": "HELD_UP_BY", "o": inc,
            "at": D(dstr(max(plus(inc_open[inc], 1), plus(order_date[o], 1)))),
            "state": "held", "hours": 4 + i * 2} for i, (o, inc) in enumerate(held)]
MITIGATIONS = [
    "rolled the checkout deploy back one revision",
    "paused the partial restock feed and replayed it whole",
    "failed Harbour District dispatches over to Northfield DC",
    "pinned the FX rate to the previous close",
    "reprinted the wave in pick-path order",
    "raised the upload limit to 25MB",
]
mit = [("MIT-%04d" % (1 + i), inc_ids[i], MITIGATIONS[i],
        plus(inc_open[inc_ids[i]], 1)) for i in range(6)]
# The actor is the person, not the rota they happened to be on: "on-call"
# is a shift, it cannot sign anything, and being an untyped node it slipped
# through the `by: person` check that exists to catch exactly this. There is
# no separate CARRIED_OUT_BY edge any more — it said what by= says.
ts_mit = [{"s": m, "p": "MITIGATED", "o": inc, "at": D(dstr(d)),
           "by": PEOPLE[(i * 5 + 4) % 16], "state": "applied"}
          for i, (m, inc, what, d) in enumerate(mit)]
ts_res = [{"s": inc_ids[i], "p": "RESOLVED_BY", "o": PEOPLE[(i * 7 + 2) % 16],
           "at": D(dstr(plus(inc_open[inc_ids[i]], 3))), "state": "resolved",
           "postmortem": i % 3 == 0} for i in range(12)]
ts_disr = [{"s": inc_ids[(i * 5) % 12], "p": "DISRUPTED", "o": WNAMES[i % 4],
            "shifts_lost": 1 + i % 3} for i in range(4)]

inc_nodes = [
    ("the incidents themselves", [
        (n, {"type": "incident", "severity": sev, "summary": summ})
        for n, sev, summ in INCIDENTS]),
    ("what somebody actually did about them. A mitigation is an object, not\n  # a note on the incident: it has an id, the action it performed, the\n  # incident it stopped and the person who ran it",
     [(m, {"type": "mitigation", "action": what, "applied": dstr(d)})
      for m, inc, what, d in mit]),
    ("people, systems, warehouses and orders — every one of these names also\n  # exists in another member graph, so an incident is not a silo: it is\n  # attached to the same object the rest of the company is talking about",
     [(p, {"type": "person", "team": person_team[p]}) for p in PEOPLE]
     + [(s, {"type": "system", "language": lang, "owner": t}) for s, t, lang in SYSTEMS]
     + [(w, {"type": "warehouse", "region": r}) for w, r, cap in WAREHOUSES]
     + [(o, {"type": "order", "placed": dstr(order_date[o])}) for o in sorted({o for o, inc in held})]),
]

HDR_INC = """# trike goods — incidents
#
# What went wrong, to which object, and who closed it. An incident is not a
# ticket sitting in a separate tool here: it points at the same
# `inventory-service` node the org graph says commerce-platform operates, and
# the orders it stalled are the same `ORD-25131` nodes the commerce graph
# says a customer placed.
#
# The lifecycle open -> resolved is two dated actions on the incident, so
# `state('INC-2025-03')` is an answer rather than a field. AFFECTED and
# DISRUPTED carry no date, because they say what the incident is *about* —
# which is not something that happened at a time.
#
# The mitigation in between is its own object. It is a thing somebody did,
# with an operator and a time of its own, so MIT-0001 points *at* the
# incident rather than hanging off it. `history('INC-2025-01')` still reads
# it — history folds both directions — while `state('INC-2025-01')` stays
# the incident's own, which is what keeps 'applied' off the incident and off
# the engineer who ran it."""

write("trike_incidents.yaml", HDR_INC, preds_inc, inc_nodes, [
    ("someone noticed", ts_raised),
    ("what it was about", ts_aff + ts_disr),
    ("the orders it stalled — the event hangs off the order, because the\norder is what stopped moving", ts_held),
    ("what stopped the bleeding — the mitigation object. Who ran it is the\n"
     "actor of the action itself (by=), which MITIGATED declares must be a\n"
     "person: a mitigation nobody signed is refused.", ts_mit),
    ("and who closed it", ts_res),
])

# ============================================================== workspace
open(os.path.join(OUT, "trike_workspace.yaml"), "w").write("""\
# trike goods demo workspace — a read-only union of the five member graphs.
#
# trike goods is a fictional homeware and pantry retailer. Each member graph
# is owned by a different team and is a normal trikedb file on its own; the
# workspace reads them together, so a question can cross from an order to
# the warehouse it shipped from to the team that staffs that warehouse
# without anybody merging the files.
#
# regenerate the page:
#   trikedb ui generate examples/trike_workspace.yaml -o docs/index.html \\
#       --title "trike goods · operations ontology"
graphs:
  catalog: trike_catalog.yaml
  commerce: trike_commerce.yaml
  fulfilment: trike_fulfilment.yaml
  org: trike_org.yaml
  incidents: trike_incidents.yaml
""")
print("trike_workspace.yaml")
