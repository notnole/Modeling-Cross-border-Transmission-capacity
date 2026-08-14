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

# Directed borders that have monthly BASE forwards on both legs.
PRICEABLE_BORDERS = [
    "sk_hu", "hu_sk",
    "sk_cz", "cz_sk",
    "cz_de", "de_cz",
    "at_de", "de_at",
    "hu_ro", "ro_hu",
]
