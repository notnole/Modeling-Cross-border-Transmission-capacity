"""Zone code maps.

EEX short-code roots are taken from `plumbing/eex/catalog.md` (audited
2026-08-03) — they are NOT the area codes, so never guess one.
"""

# EEX product root -> our zone code (the column name in Data/spot_current.csv
# and the key in DataBorderClass.dictionary_borders).
EEX_ROOT_TO_ZONE = {
    "AT": "at",
    "DE": "de",
    "F7": "fr",
    "F9": "hu",
    "FD": "it",   # IT_NORD on the spot side
    "FF": "gr",
    "FH": "ro",
    "FX": "cz",
    "FY": "sk",
    "Q0": "nl",
    # FP / PLPX (Poland) carry Year contracts only -> unusable for a monthly
    # capacity right; deliberately not mapped.
}

# our zone code -> ENTSO-E area code accepted by plumbing.entsoe
ZONE_TO_ENTSOE = {
    "sk": "SK",
    "cz": "CZ",
    "hu": "HU",
    "at": "AT",
    "de": "DE_LU",
    "ro": "RO",
    "pl": "PL",
    "it": "IT_NORD",
    "fr": "FR",
    "nl": "NL",
}

# SK comes from OKTE (the source of truth for the Slovak DAM print), every
# other zone from ENTSO-E.
OKTE_ZONES = ("sk",)

# Directed zone pairs with monthly BASE forwards on both legs. This is the
# PRICING key: one sigma and one pair of forward closes per entry.
PRICEABLE_BORDERS = [
    "sk_hu", "hu_sk",
    "sk_cz", "cz_sk",
    "cz_de", "de_cz",
    "at_de", "de_at",
    "hu_ro", "ro_hu",
]

# JAO auction corridor -> the zone pair that prices it. This is a MANY-TO-ONE
# map and that is the whole point: `CZ-DE` / `DE-CZ` run no monthly auction, but
# the German TSO-split corridors do, and `DE`, `DE(50Hz)` and `DE(TenneT)` are
# all the same **price zone** (`DE_LU`) per plumbing/jao_auctions/catalog.md.
# So the four corridors below carry IDENTICAL cz/de forwards and an identical
# fitted sigma, and differ only in ATC, gate and availability.
#
# Maintenance: the 50Hz pair averages ~172 h/month of reduced ATC against
# TenneT's ~0-4 h, and `maintenance_min_atc_mw` is **0** in most of those months,
# so even a 1 MW holder is physically out. That does NOT reduce the per-MWh
# value: under HAR Art 59 a curtailed holder is made whole at the same
# `max(spread, 0)` a non-nominated holder receives under UIOSI, so
# plumbing/jao_auctions/catalog.md is explicit that realised value per MWh
# "must not be reduced for it". All 7,728 observed curtailment records read
# `Network Security` (Art 59), not force majeure (Art 60, which WOULD change it
# — there you get the clearing price back, so the margin is 0).
# The residual risk is the Art 59(2)-(4) compensation cap: over the cap all
# holders are cut pro rata. Not quantifiable without JAO's cap figures, and it
# bites hardest on exactly these heavily-curtailed corridors.
CORRIDOR_TO_BORDER = {
    "SK-HU": "sk_hu", "HU-SK": "hu_sk",
    "SK-CZ": "sk_cz", "CZ-SK": "cz_sk",
    "AT-DE": "at_de", "DE-AT": "de_at",
    "HU-RO": "hu_ro", "RO-HU": "ro_hu",
    "DE(50Hz)-CZ": "de_cz", "DE(TenneT)-CZ": "de_cz",
    "CZ-DE(50Hz)": "cz_de", "CZ-DE(TenneT)": "cz_de",
}
# Corridors whose auction is the CEEXD joint auction, not one of their own.
JOINT_AUCTION_CORRIDORS = {"DE(50Hz)-CZ", "CZ-DE(50Hz)"}
