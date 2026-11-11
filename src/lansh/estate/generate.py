"""
Generate SynthInsure, the synthetic Irish insurer behind the legacy estate (plan §7.1).

SynthInsure sells motor, home and travel cover from 2019 to 2025 and reports as of
2025-12-31. The generator writes the nine source extracts (the bronze ``stg`` tables) as
Parquet, plus CSV copies and a manifest of hashes.

Rules:

- **Deterministic.** One seeded NumPy generator and one seeded Faker, used in a fixed order,
  so the same seed gives byte-identical files on every machine with the same lock file.
  Adding, removing or moving a single random draw therefore changes the committed extracts.
- **Synthetic only.** Names and addresses are fictional (Faker ``en_IE`` plus curated Irish
  names); emails use the reserved ``.example`` domain; there are no phone numbers.
- **Edge cases are planted on purpose**, together with the conditions each planted legacy bug
  needs in order to show up. ``tests/test_generate.py`` checks every one of them. The trap
  and bug ids in the docstrings and comments below are those of plan Appendices A and B.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from faker import Faker

from lansh import __version__
from lansh.config import DATA_DIR, REPO_ROOT
from lansh.contracts import TableFingerprint, TableSchema
from lansh.estate.fingerprint import content_sha256, file_sha256
from lansh.estate.inventory import parse_yaml

log = logging.getLogger(__name__)

SEED = 20251231
AS_OF = dt.date(2025, 12, 31)
START = dt.date(2019, 1, 1)
SNAPSHOT_DATES = (dt.date(2025, 6, 30), dt.date(2025, 12, 31))
"""The dates of the two policy snapshots; each holds every term that had started by then."""
# 20,000 customers hold about 60,000 policy terms: at a realistic claim frequency that is
# about 3,000 claims, enough to plant every claim-side edge case many times over
N_CUSTOMERS = 20_000
# claims per policy-year by line of business, near a real Irish book's, so paid claims come
# to about 60-75% of earned premium
CLAIM_FREQUENCY = {"MOT": 0.078, "HOM": 0.052, "TRV": 0.05}
DICTIONARY_PATH = DATA_DIR / "dictionary.yaml"
DAY = dt.timedelta(days=1)
# a registration in the format T08's motor test accepts, such as 191-D-12345 or 12-KY-123
VALID_REG = re.compile(r"^\d{2,3}-[A-Z]{1,2}-\d+$")

### Reference lists (public geography and common Irish names; no real people)

COUNTY_TOWNS: dict[str, tuple[int, list[str]]] = {
    # county: (relative weight, towns)
    "Dublin": (280, ["Dublin", "Swords", "Tallaght", "Dún Laoghaire", "Lucan", "Balbriggan"]),
    "Cork": (110, ["Cork", "Mallow", "Cobh", "Youghal", "Bandon", "Clonakilty"]),
    "Galway": (55, ["Galway", "Tuam", "Ballinasloe", "Loughrea", "Clifden"]),
    "Kildare": (48, ["Naas", "Newbridge", "Maynooth", "Athy", "Celbridge"]),
    "Meath": (45, ["Navan", "Trim", "Ashbourne", "Kells"]),
    "Limerick": (42, ["Limerick", "Newcastle West", "Abbeyfeale", "Kilmallock"]),
    "Donegal": (34, ["Letterkenny", "Buncrana", "Donegal", "Bundoran"]),
    "Tipperary": (34, ["Clonmel", "Nenagh", "Thurles", "Cashel"]),
    "Kerry": (32, ["Tralee", "Killarney", "Listowel", "Dingle"]),
    "Wexford": (33, ["Wexford", "Enniscorthy", "Gorey", "New Ross"]),
    "Wicklow": (32, ["Bray", "Wicklow", "Arklow", "Greystones"]),
    "Mayo": (29, ["Castlebar", "Ballina", "Westport", "Claremorris"]),
    "Louth": (30, ["Dundalk", "Drogheda", "Ardee"]),
    "Clare": (27, ["Ennis", "Shannon", "Kilrush", "Kilkee"]),
    "Waterford": (27, ["Waterford", "Dungarvan", "Tramore"]),
    "Kilkenny": (23, ["Kilkenny", "Castlecomer", "Thomastown"]),
    "Westmeath": (21, ["Mullingar", "Athlone", "Moate"]),
    "Laois": (20, ["Portlaoise", "Portarlington", "Mountmellick"]),
    "Offaly": (18, ["Tullamore", "Birr", "Edenderry"]),
    "Cavan": (17, ["Cavan", "Bailieborough", "Cootehill"]),
    "Sligo": (15, ["Sligo", "Tubbercurry", "Ballymote"]),
    "Roscommon": (15, ["Roscommon", "Boyle", "Castlerea"]),
    "Monaghan": (14, ["Monaghan", "Carrickmacross", "Castleblayney"]),
    "Carlow": (13, ["Carlow", "Tullow", "Bagenalstown"]),
    "Longford": (10, ["Longford", "Granard", "Ballymahon"]),
    "Leitrim": (8, ["Carrick-on-Shannon", "Manorhamilton", "Mohill"]),
}
ROUTING_KEYS = {
    "Dublin": ["D01", "D02", "D04", "D06", "D08", "D12", "D15", "D24", "A94", "A96", "K67"],
    "Cork": ["T12", "T23", "P31", "P43", "P72"],
    "Galway": ["H91", "H53", "H65"],
    "Kildare": ["W91", "W23", "R14"],
    "Meath": ["C15", "A85", "A84"],
    "Limerick": ["V94", "V42"],
    "Donegal": ["F92", "F93", "F94"],
    "Tipperary": ["E91", "E45"],
    "Kerry": ["V92", "V93", "V31"],
    "Wexford": ["Y35", "Y21", "Y25"],
    "Wicklow": ["A98", "A63", "A67"],
    "Mayo": ["F23", "F26", "F28"],
    "Louth": ["A91", "A92"],
    "Clare": ["V95", "V14"],
    "Waterford": ["X91", "X35"],
    "Kilkenny": ["R95"],
    "Westmeath": ["N91", "N37"],
    "Laois": ["R32"],
    "Offaly": ["R35", "R42"],
    "Cavan": ["H12"],
    "Sligo": ["F91"],
    "Roscommon": ["F42", "F45"],
    "Monaghan": ["H18"],
    "Carlow": ["R93"],
    "Longford": ["N39"],
    "Leitrim": ["N41"],
}
"""Eircode routing keys (an Eircode's first three characters) used in each county."""
BORDER_COUNTIES = {"Donegal", "Monaghan", "Louth", "Cavan", "Leitrim"}
"""Counties on the border with Northern Ireland, where some cover is written in sterling."""
REG_CODES = {
    "Dublin": "D",
    "Cork": "C",
    "Galway": "G",
    "Kildare": "KE",
    "Meath": "MH",
    "Limerick": "L",
    "Donegal": "DL",
    "Tipperary": "T",
    "Kerry": "KY",
    "Wexford": "WX",
    "Wicklow": "WW",
    "Mayo": "MO",
    "Louth": "LH",
    "Clare": "CE",
    "Waterford": "W",
    "Kilkenny": "KK",
    "Westmeath": "WH",
    "Laois": "LS",
    "Offaly": "OY",
    "Cavan": "CN",
    "Sligo": "SO",
    "Roscommon": "RN",
    "Monaghan": "MN",
    "Carlow": "CW",
    "Longford": "LD",
    "Leitrim": "LM",
}
"""The county index mark in an Irish vehicle registration, such as KE in 191-KE-1234."""
IRISH_FIRST = [
    "Seán",
    "Siobhán",
    "Pádraig",
    "Aoife",
    "Niamh",
    "Órla",
    "Éamon",
    "Máire",
    "Caoimhín",
    "Ciarán",
    "Dónal",
    "Fionnuala",
    "Sinéad",
    "Róisín",
    "Méabh",
    "Tadhg",
    "Oisín",
    "Ríona",
    "Bríd",
    "Séamus",
    "Áine",
    "Clíona",
    "Darragh",
    "Eoghan",
    "Saoirse",
    "Cathal",
    "Gráinne",
    "Muireann",
    "Labhrás",
    "Éabha",
]
IRISH_LAST = [
    "Ó Briain",
    "Ó Súilleabháin",
    "Mac Cárthaigh",
    "Ní Bhriain",
    "O'Brien",
    "O'Sullivan",
    "Ó Dónaill",
    "Ó Ceallaigh",
    "Ní Chonaill",
    "O'Connor",
    "O'Neill",
    "Mac Giolla Phádraig",
    "Ó Máille",
    "Ní Mhurchú",
    "O'Donoghue",
    "Ó Gríofa",
    "Mac Mathúna",
    "Ó Riain",
    "O'Reilly",
    "Ní Dhomhnaill",
]
LONG_LAST = [
    "Fitzgerald-Ó Súilleabháin-Mac Giolla Phádraig",
    "Ní Chonchubhair-Breathnach-Ó Ceallacháin-Ruiséal",
    "Mac Con Uladh-Ó Cinnéide-FitzGibbon-Breathnach",
    "Ó Murchadha-Mac an tSaoir-de Búrca-Ó Flaithearta",
]
STREETS = [
    "Main Street",
    "Church Road",
    "Bóthar na Trá",
    "St. Patrick's Terrace",
    "Mill Lane",
    "Green Road",
    "Strand Road",
    "College Park",
    "Seaview Avenue",
    "Ard na Gréine",
    "Fairgreen",
    "Bridge Street",
    "Castle Court",
    "Sráid an Mhuilinn",
    "Oak Drive",
    "Station Road",
    "The Crescent",
    "Woodlawn Grove",
    "Abbey Street",
    "Cois Abhann",
]
EMAIL_DOMAINS = ["mail.example", "post.example", "inbox.example", "webmail.example"]
"""Domains under the reserved ``.example`` top-level domain, so no address can be real."""
CAUSES = {
    "MOT": ["COLL", "COLL", "COLL", "THEFT", "GLASS", "GLASS", "FIRE", "INJ"],
    "HOM": ["ESCAPE", "ESCAPE", "STORM", "FLOOD", "FIRE", "THEFT", "ACC", "ACC"],
    "TRV": ["MEDIC", "MEDIC", "BAGG", "CANX", "CANX"],
}
"""Claim cause codes by line of business; a code listed twice is drawn twice as often."""
DESCRIPTIONS = {
    "COLL": [
        "Rear-ended at junction, third party reg {reg}",
        "Collision in car park",
        "Hit kerb and damaged alloy; third party vehicle {reg} involved",
        "Low speed collision at roundabout",
    ],
    "THEFT": [
        "Vehicle stolen from driveway overnight",
        "Break-in, items taken",
        "Theft of contents from shed",
    ],
    "GLASS": ["Windscreen cracked by stone chip", "Rear window smashed"],
    "FIRE": ["Kitchen fire, smoke damage to 2 rooms", "Vehicle fire after electrical fault"],
    "INJ": ["Whiplash claimed by passenger", "Third party injury at junction; reg {reg}"],
    "ESCAPE": [
        "Burst pipe in attic, ceiling down",
        "Leak from dishwasher damaged floor",
        "Escape of water from upstairs bathroom",
    ],
    "STORM": ["Storm damage to roof tiles", "Fence and shed damaged in storm"],
    "FLOOD": ["River flooding, ground floor affected", "Flash flood in basement"],
    "ACC": ["Accidental damage to TV", "Paint spilled on carpet", "Dropped laptop"],
    "MEDIC": ["Hospital treatment abroad", "Emergency dental treatment while travelling"],
    "BAGG": ["Baggage lost by airline", "Suitcase damaged in transit"],
    "CANX": ["Trip cancelled due to illness", "Flight cancelled, accommodation lost"],
}
"""Claim description templates by cause; ``{reg}`` takes a vehicle registration."""
PAYEES = ["CLAIMANT", "GARAGE", "SOLICITOR", "SUPPLIER", "HOSPITAL", "LOSS ADJ"]


def policy_number(t: Term) -> str:
    """
    Format a term's policy number as ``<LOB>/<inception year>/<six digits>``.

    Args:
        t: The policy term.

    Returns:
        The policy number, such as ``MOT/2024/500123``.
    """
    return f"{t.lob}/{t.inception.year}/{t.policy_id % 1_000_000:06d}"


def _easter(year: int) -> dt.date:
    """
    Find Easter Sunday by the anonymous Gregorian algorithm (Meeus/Jones/Butcher).

    The FX rates use it to leave out Good Friday and Easter Monday.
    """
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return dt.date(year, month, day + 1)


def ascii_fold(text: str) -> str:
    """
    Strip accents, and drop any other character that isn't ASCII.

    Args:
        text: Text such as a name with fadas.

    Returns:
        The ASCII text: ``Seán`` becomes ``Sean``.
    """
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def add_months(d: dt.date, months: int) -> dt.date:
    """
    Add calendar months, clamping to the month's end (like T-SQL DATEADD).

    Args:
        d: The start date.
        months: Months to add; may be negative.

    Returns:
        The date ``months`` later: 31 January 2024 plus one month is 29 February.
    """
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    raise AssertionError("unreachable")


def cents(value: float) -> Decimal:
    """
    Round an amount to whole cents, as an exact Decimal.

    Args:
        value: An amount in currency units.

    Returns:
        The amount with two decimal places.
    """
    return Decimal(round(value * 100)).scaleb(-2)


### The generator


@dataclass
class Term:
    """
    One policy term (a policy_id) and its life story.

    Attributes:
        line_id: The customer's line of cover, shared by all its terms (renewals or trips).
        lob: Line of business: ``MOT``, ``HOM`` or ``TRV``.
        premium: The term's premium before any mid-term adjustment.
        broker: Broker code, or None for direct business.
        frequency: Payment frequency: ``ANNUAL`` or ``MONTHLY``.
        ncd: No-claims discount in years (motor only).
        renewal: True when this term renews an earlier one.
        renewed: True when a later term renews this one.
        mta_on: Date of the mid-term adjustment, if there is one.
        mta_premium: The premium from the mid-term adjustment on.
        status_variant: Sticky non-canonical spelling of the status (``title`` or ``pad``).
        product_variant: Sticky keying variant of the product code (``lower`` or ``pad``).
        broker_variant: Sticky keying variant of the broker code (``lower``, ``pad`` or
            ``title``).
        reg_snap1: Vehicle registration in the first snapshot.
        reg_snap2: Vehicle registration in the second snapshot.
        broker_snap2: Broker code in the second snapshot; the first shows ``broker``.
    """

    policy_id: int
    line_id: int
    customer_id: int
    product_code: str
    lob: str
    inception: dt.date
    expiry: dt.date
    premium: Decimal
    currency: str
    broker: str | None
    sum_insured: Decimal | None
    frequency: str
    vehicle_reg: str | None
    ncd: int | None
    renewal: bool
    cancelled_on: dt.date | None = None
    renewed: bool = False
    mta_on: dt.date | None = None
    mta_premium: Decimal | None = None
    status_variant: str | None = None
    product_variant: str | None = None
    broker_variant: str | None = None
    reg_snap1: str | None = None
    reg_snap2: str | None = None
    broker_snap2: str | None = None


@dataclass
class SynthInsure:
    """
    The seeded generator of SynthInsure's source tables, as lists of row dicts.

    :meth:`build` calls the table builders in a fixed order. Every random draw comes from
    ``rng`` or ``fake``, so calling the builders in another order, or adding a draw, changes
    everything generated after that point.

    Attributes:
        seed: Seed for both ``rng`` and ``fake``.
        n_customers: How many customers to generate; tests use fewer, for speed.
        rng: The NumPy generator behind every draw except Faker's names.
        fake: Faker (``en_IE``) for names, seeded the same way.
        _early_gbp: How many sterling lines have been moved to the first days of 2019 (six
            at most).
    """

    seed: int = SEED
    n_customers: int = N_CUSTOMERS
    rng: np.random.Generator = field(init=False)
    fake: Faker = field(init=False)
    _early_gbp: int = 0

    def __post_init__(self) -> None:
        """
        Seed the NumPy generator and Faker from ``seed``.
        """
        self.rng = np.random.default_rng(self.seed)
        self.fake = Faker("en_IE")
        self.fake.seed_instance(self.seed)

    ### Small helpers
    def chance(self, p: float) -> bool:
        """
        Toss a biased coin.

        Args:
            p: Probability of True, from 0 to 1.

        Returns:
            True with probability ``p``.
        """
        return bool(self.rng.random() < p)

    def pick(self, items: Sequence[Any]) -> Any:
        """
        Pick one item, each equally likely.

        Args:
            items: A non-empty sequence.

        Returns:
            The chosen item.
        """
        return items[int(self.rng.integers(len(items)))]

    def weighted(self, items: list[Any], weights: list[float]) -> Any:
        """
        Pick one item with probability in proportion to its weight.

        Args:
            items: The items to pick from.
            weights: Relative weight of each item; they needn't add up to 1.

        Returns:
            The chosen item.
        """
        w = np.asarray(weights, dtype=float)
        return items[int(self.rng.choice(len(items), p=w / w.sum()))]

    def date_between(self, lo: dt.date, hi: dt.date) -> dt.date:
        """
        Pick a date between two dates, both included, each equally likely.

        Args:
            lo: The earliest date.
            hi: The latest date. When it isn't after ``lo``, ``lo`` comes back and no random
                number is drawn.

        Returns:
            The chosen date.
        """
        if hi <= lo:
            return lo
        return lo + dt.timedelta(days=int(self.rng.integers((hi - lo).days + 1)))

    def lognormal(self, median: float, sigma: float) -> float:
        """
        Draw from a log-normal distribution with the given median.

        Args:
            median: The distribution's median.
            sigma: Standard deviation of the value's logarithm.

        Returns:
            A positive value.
        """
        return float(median * np.exp(self.rng.normal(0.0, sigma)))

    ### Products and brokers
    def products(self) -> list[dict[str, Any]]:
        """
        Build the product catalogue: eight motor, home and travel products.

        MOT-TPO was withdrawn on 2023-06-30, and TRV-SGL (single trip) has no fixed term.

        Returns:
            One row per product.
        """
        rows = [
            ("MOT-COMP", "Motor Comprehensive", "MOT", 12, "2015-01-01", None),
            ("MOT-TPFT", "Motor Third Party, Fire and Theft", "MOT", 12, "2015-01-01", None),
            ("MOT-TPO", "Motor Third Party Only", "MOT", 12, "2015-01-01", "2023-06-30"),
            ("HOM-BLD", "Home Buildings", "HOM", 12, "2015-01-01", None),
            ("HOM-CNT", "Home Contents", "HOM", 12, "2015-01-01", None),
            ("HOM-BC", "Home Buildings and Contents", "HOM", 12, "2018-03-01", None),
            ("TRV-ANN", "Travel Annual Multi-Trip", "TRV", 12, "2016-05-01", None),
            ("TRV-SGL", "Travel Single Trip", "TRV", None, "2016-05-01", None),
        ]
        return [
            {
                "product_code": code,
                "product_name": name,
                "lob_code": lob,
                "term_months": term,
                "levy_rate": Decimal("0.0300"),
                "launched_on": dt.date.fromisoformat(launched),
                "withdrawn_on": dt.date.fromisoformat(w) if w else None,
            }
            for code, name, lob, term, launched, w in rows
        ]

    def brokers(self) -> list[dict[str, Any]]:
        """
        Build the broker register: 40 ``BRKnnn`` codes and five shorter ``BKnnn`` codes.

        The short codes are space-padded to CHAR(6), so they match the codes on policies only
        when trailing spaces are ignored (TSQL-02). Two brokers are 'Active' in title case
        and two have no region.

        Returns:
            One row per broker.
        """
        regions = ["Dublin", "Leinster", "Munster", "Connacht", "Ulster"]
        rows = []
        codes = [f"BRK{i:03d}" for i in range(1, 41)] + [f"BK{i:03d}" for i in range(101, 106)]
        for i, code in enumerate(codes):
            surname = self.fake.last_name()
            style = self.pick(
                [
                    "{s} Insurance Brokers",
                    "{s} & Co. Insurances",
                    "{t} Financial Services",
                    "{s} Brokers Ltd",
                ]
            )
            town = self.pick(COUNTY_TOWNS[self.pick(list(COUNTY_TOWNS))][1])
            status = "INACTIVE" if i % 9 == 4 else "ACTIVE"
            if i in (7, 23):
                status = "Active"
            rows.append(
                {
                    "broker_code": code.ljust(6),  # CHAR(6): shorter codes are space-padded
                    "broker_name": style.format(s=surname, t=town),
                    "region": None if i in (11, 31) else self.pick(regions),
                    "commission_rate": Decimal(int(self.rng.integers(20, 61)) * 25).scaleb(-4),
                    "status": status,
                    "appointed_date": self.date_between(dt.date(2005, 1, 1), dt.date(2022, 12, 31)),
                }
            )
        return rows

    ### Customers
    def _person(self) -> dict[str, Any]:
        """
        Draw a first name, last name and county; 22% get curated Irish names.
        """
        if self.chance(0.22):
            first, last = self.pick(IRISH_FIRST), self.pick(IRISH_LAST)
        else:
            first, last = self.fake.first_name(), self.fake.last_name()
        county = self.weighted(list(COUNTY_TOWNS), [w for w, _ in COUNTY_TOWNS.values()])
        return {"first_name": first, "last_name": last, "county": county}

    def _address(self, county: str) -> tuple[str, str, str | None]:
        """
        Draw an address line, town and Eircode in a county.

        Eircodes are keyed inconsistently on purpose (TSQL-15): some are missing, too short
        or end in a space, and some lack the space after the routing key.
        """
        town = self.pick(COUNTY_TOWNS[county][1])
        number = int(self.rng.integers(1, 180))
        street = self.pick(STREETS)
        line1 = f"{number} {street}" if not self.chance(0.15) else f"Apt {number}, {street}"
        key = self.pick(ROUTING_KEYS[county])
        unique = "".join(self.pick("ACDEFHKNPRTVWXY0123456789") for _ in range(4))
        roll = self.rng.random()
        if roll < 0.05:
            eircode = None
        elif roll < 0.07:
            eircode = f"{key}{unique[:3]}"  # too short: keyed wrongly
        elif roll < 0.10:
            eircode = f"{key}{unique} "  # trailing space
        elif roll < 0.40:
            eircode = f"{key}{unique}"
        else:
            eircode = f"{key} {unique}"
        return line1, town, eircode

    def _email(self, first: str, last: str, n: int) -> str:
        """
        Build an email address on one of the reserved ``.example`` domains.

        Accents are folded and apostrophes and spaces dropped, so Seán Ó Briain with ``n``
        17 gets ``sean.obriain17@`` and a random domain.
        """
        local = f"{ascii_fold(first)}.{ascii_fold(last)}".replace("'", "").replace(" ", "")
        return f"{local.lower()}{n}@{self.pick(EMAIL_DOMAINS)}"

    def customers(self) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
        """
        Build the customer extract: ``n_customers`` people with one to three CRM versions each.

        Planted on purpose: over-long surnames and address lines, leap-day birthdays, a few
        missing dates of birth, segment code ``STD `` padded to CHAR(4) (TSQL-02), source
        systems keyed in different cases or padded, and people registered twice.

        Returns:
            The extract rows (every version, with keying noise) and each customer's current
            record by customer id.
        """
        people: dict[int, dict[str, Any]] = {}
        for i in range(self.n_customers):
            cid = 100_001 + i
            p = self._person()
            if i % 500 == 17:
                p["last_name"] = self.pick(LONG_LAST)  # over-long double-barrelled names
            age_days = int(self.rng.integers(18 * 365 + 5, 89 * 365))
            dob: dt.date | None = AS_OF - dt.timedelta(days=age_days)
            if i % 400 == 3:
                leap_year = self.pick(
                    [1964, 1968, 1972, 1976, 1980, 1984, 1988, 1992, 1996, 2000, 2004]
                )
                dob = dt.date(leap_year, 2, 29)
            if self.chance(0.004):
                dob = None
            since_years = min(20.0, float(self.rng.exponential(6.0)))
            since = AS_OF - dt.timedelta(days=int(since_years * 365.25))
            # no one becomes a customer before turning 18
            if dob and since < add_months(dob, 18 * 12):
                since = min(AS_OF, add_months(dob, 18 * 12))
            line1, town, eircode = self._address(p["county"])
            if i % 500 == 29:
                line1 = (
                    f"Apartment {int(self.rng.integers(1, 99))}, Block C, The Old Distillery "
                    f"Quarter, {self.pick(STREETS)}, Upper Baile an Mhuilinn"
                )  # over-long
            people[cid] = {
                "customer_id": cid,
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "email": None
                if self.chance(0.04)
                else self._email(p["first_name"], p["last_name"], i % 97),
                "date_of_birth": dob,
                "address_line1": line1,
                "town": town,
                "county": p["county"],
                "eircode": eircode,
                "segment_code": self.weighted(["GOLD", "SILV", "STD ", None], [15, 25, 55, 5]),
                "marketing_opt_in": self.weighted(["Y", "N", None], [40, 50, 10]),
                "customer_since": since,
                "source_system": self.weighted(
                    ["CRM", "WEB", "BROKER", "Web", "web "], [50, 30, 18, 1, 1]
                ),
            }
        self._plant_email_duplicates(people)
        rows = self._customer_versions(people)
        return rows, people

    def _plant_email_duplicates(self, people: dict[int, dict[str, Any]]) -> None:
        """
        Plant 130 people registered twice, with emails differing only in case or padding.

        The second customer takes the first's name and date of birth, and an email that
        equals the first's only when case and trailing spaces are ignored (TSQL-01).
        """
        ids = [cid for cid, p in people.items() if p["email"]]
        chosen = self.rng.choice(len(ids), size=260, replace=False)
        for a_idx, b_idx in zip(chosen[0::2], chosen[1::2], strict=True):
            a, b = people[ids[int(a_idx)]], people[ids[int(b_idx)]]
            local, domain = a["email"].split("@")
            variant = self.pick(["title", "upper", "pad", "mixed"])
            if variant == "title":
                email = local.title() + "@" + domain
            elif variant == "upper":
                email = a["email"].upper()
            elif variant == "pad":
                email = a["email"] + " "
            else:
                email = local[:1].upper() + local[1:] + "@" + domain.capitalize()
            for key in ("first_name", "last_name", "date_of_birth"):
                b[key] = a[key]
            b["email"] = email

    def _customer_versions(self, people: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Expand each customer into one to three CRM versions, stamped with ``updated_at``.

        Older versions hold what the record used to say, so keeping the oldest version
        (BUG-01) picks up stale values. For some customers two versions share a timestamp,
        so ``updated_at`` alone doesn't order them.
        """
        rows: list[dict[str, Any]] = []
        for cid, person in people.items():
            n_versions = self.weighted([1, 2, 3], [84, 13, 3])
            since_ts = dt.datetime.combine(person["customer_since"], dt.time(9)) + dt.timedelta(
                seconds=int(self.rng.integers(0, 9 * 3600))
            )
            end_ts = dt.datetime(2025, 12, 31, 18, 0, 0)
            stamps = sorted(
                since_ts + (end_ts - since_ts) * float(x) for x in self.rng.random(n_versions - 1)
            )
            stamps = [since_ts, *[s.replace(microsecond=0) for s in stamps]]
            tie = n_versions > 1 and cid % 97 == 5
            if tie:
                stamps[1] = stamps[0]  # two saves in the same second
            versions = [dict(person)]
            for _ in range(n_versions - 1):
                versions.append(self._changed(versions[-1]))
            # the latest version is the truth and older ones are what the CRM said before,
            # so the oldest version gets the earliest timestamp
            for v, stamp in zip(reversed(versions), stamps, strict=True):
                v = dict(v)
                v["updated_at"] = stamp
                rows.append(v)
        rows.sort(key=lambda r: (r["updated_at"], r["customer_id"]))
        for r in rows:
            self._casing(r)
        return rows

    def _changed(self, prev: dict[str, Any]) -> dict[str, Any]:
        """
        Derive an older version of a customer record: something about it was different.

        It changes one of: the address (a move), email, segment, opt-in, surname, or the
        county's case.
        """
        v = dict(prev)
        what = self.weighted(
            ["move", "email", "segment", "optin", "name", "case"], [40, 22, 15, 10, 5, 8]
        )
        if what == "move":
            county = self.weighted(list(COUNTY_TOWNS), [w for w, _ in COUNTY_TOWNS.values()])
            v["county"] = county
            v["address_line1"], v["town"], v["eircode"] = self._address(county)
        elif what == "email":
            v["email"] = (
                None
                if self.chance(0.3)
                else self._email(v["first_name"], v["last_name"], int(self.rng.integers(100, 999)))
            )
        elif what == "segment":
            v["segment_code"] = self.pick(["GOLD", "SILV", "STD "])
        elif what == "optin":
            v["marketing_opt_in"] = self.pick(["Y", "N"])
        elif what == "name":
            v["last_name"] = self.fake.last_name()
        else:
            v["county"] = v["county"].upper() if v["county"] else v["county"]
        return v

    def _casing(self, row: dict[str, Any]) -> None:
        """
        Add keying noise: case and trailing-space variants of the county (TSQL-01, TSQL-02).

        A few counties go missing, and about 1% of first names get a trailing space.
        """
        county = row["county"]
        if county is None:
            return
        roll = self.rng.random()
        if roll < 0.004:
            row["county"] = None
        elif roll < 0.034:
            row["county"] = county.upper()
        elif roll < 0.044:
            row["county"] = county.lower()
        elif roll < 0.064:
            row["county"] = county + " "
        if self.chance(0.01):
            row["first_name"] = row["first_name"] + " "

    ### Policies
    def _premium(self, product: str, age: int | None, ncd: int | None) -> Decimal:
        """
        Price a term: a base rate per product, with age and no-claims factors for motor.

        Motor drivers under 25 pay 1.9 times the base rate and those over 70 pay 1.25 times,
        less 6% per no-claims year. Log-normal noise goes on top.
        """
        base = {
            "MOT-COMP": 680,
            "MOT-TPFT": 490,
            "MOT-TPO": 390,
            "HOM-BLD": 330,
            "HOM-CNT": 190,
            "HOM-BC": 460,
            "TRV-ANN": 95,
            "TRV-SGL": 38,
        }[product]
        factor = 1.0
        if product.startswith("MOT"):
            if age is not None and age < 25:
                factor *= 1.9
            elif age is not None and age > 70:
                factor *= 1.25
            factor *= 1.0 - 0.06 * (ncd or 0)
        return cents(self.lognormal(base * factor, 0.22))

    def _reg(self, county: str, year: int) -> str:
        """
        Make an Irish vehicle registration, such as ``191-D-12345`` or ``12-KY-345``.

        From 2013 the year carries a half-year digit (131, 132). A county without an index
        mark gets Dublin's.
        """
        code = REG_CODES.get(county, "D")
        if year >= 2013:
            half = self.pick([1, 2])
            return f"{year % 100:02d}{half}-{code}-{int(self.rng.integers(1, 99999))}"
        return f"{year % 100:02d}-{code}-{int(self.rng.integers(1, 9999))}"

    def policies(
        self,
        people: dict[int, dict[str, Any]],
        brokers: list[dict[str, Any]],
    ) -> list[Term]:
        """
        Build every policy term: one to three lines of cover per customer, renewed yearly.

        A line starts after the customer joined and renews until it lapses, is cancelled or
        passes the as-of date; single-trip travel is one short term per trip. Some cover in
        the border counties is in sterling and some travel cover in dollars, and about 2% of
        motor lines have a malformed registration such as ``TBC`` or ``d-12345`` (TSQL-14).

        Args:
            people: Each customer's current record, by customer id.
            brokers: The broker register. New business goes only to brokers whose status
                isn't ``INACTIVE``.

        Returns:
            Every term, with the planted policy conditions applied.
        """
        broker_codes = [b["broker_code"].rstrip() for b in brokers if b["status"] != "INACTIVE"]
        terms: list[Term] = []
        line_id = 0
        next_policy = 500_001
        for cid, person in people.items():
            n_lines = self.weighted([1, 2, 3], [55, 32, 13])
            lobs = list(
                self.rng.choice(
                    ["MOT", "HOM", "TRV"], size=n_lines, replace=False, p=[0.55, 0.30, 0.15]
                )
            )
            age = None
            if person["date_of_birth"]:
                age = (AS_OF - person["date_of_birth"]).days // 365
            for lob in lobs:
                line_id += 1
                if lob == "MOT":
                    product = self.weighted(["MOT-COMP", "MOT-TPFT", "MOT-TPO"], [60, 30, 10])
                elif lob == "HOM":
                    product = self.weighted(["HOM-BLD", "HOM-CNT", "HOM-BC"], [25, 25, 50])
                else:
                    product = self.weighted(["TRV-ANN", "TRV-SGL"], [60, 40])
                currency = "EUR"
                if person["county"] in BORDER_COUNTIES and self.chance(0.35):
                    currency = "GBP"
                if lob == "TRV" and self.chance(0.06):
                    currency = "USD"
                broker = self.pick(broker_codes) if self.chance(0.45) else None
                frequency = self.weighted(["ANNUAL", "MONTHLY"], [60, 40])
                first_start = self.date_between(max(person["customer_since"], START), AS_OF)
                if (
                    currency == "GBP"
                    and lob != "TRV"
                    and self._early_gbp < 6
                    and person["customer_since"] <= dt.date(2019, 1, 1)
                ):
                    # sterling cover starting in the first days of 2019, booked before the
                    # first published exchange rate (2 January 2019): no rate yet (TSQL-09)
                    first_start = dt.date(2019, 1, 1) + dt.timedelta(days=self._early_gbp)
                    self._early_gbp += 1
                # the MOT-TPO product was withdrawn on 2023-06-30
                if product == "MOT-TPO" and first_start > dt.date(2023, 6, 30):
                    product = "MOT-TPFT"
                if product == "TRV-SGL":
                    for _ in range(self.weighted([1, 2, 3], [60, 30, 10])):
                        start = self.date_between(max(person["customer_since"], START), AS_OF)
                        days = int(self.rng.integers(3, 31))
                        terms.append(
                            Term(
                                policy_id=next_policy,
                                line_id=line_id,
                                customer_id=cid,
                                product_code=product,
                                lob=lob,
                                inception=start,
                                expiry=start + dt.timedelta(days=days - 1),
                                premium=self._premium(product, age, None),
                                currency=currency,
                                broker=broker,
                                sum_insured=None,
                                frequency="ANNUAL",
                                vehicle_reg=None,
                                ncd=None,
                                renewal=False,
                            )
                        )
                        next_policy += 1
                    continue
                start, renewal = first_start, False
                premium = self._premium(product, age, None)
                ncd = int(self.rng.integers(0, 10)) if lob == "MOT" else None
                reg = self._reg(person["county"] or "Dublin", int(self.rng.integers(2005, 2026)))
                if lob == "MOT":
                    premium = self._premium(product, age, ncd)
                    if self.chance(0.02):
                        reg = self.pick(["UNKNOWN", "TBC", "d-12345", "N/A"])
                insured = None
                if lob == "HOM":
                    insured = cents(self.lognormal(380_000, 0.4))
                elif lob == "MOT":
                    insured = cents(self.lognormal(16_000, 0.6))
                while start <= AS_OF:
                    expiry = add_months(start, 12) - DAY
                    term = Term(
                        policy_id=next_policy,
                        line_id=line_id,
                        customer_id=cid,
                        product_code=product,
                        lob=lob,
                        inception=start,
                        expiry=expiry,
                        premium=premium,
                        currency=currency,
                        broker=broker,
                        sum_insured=insured,
                        frequency=frequency,
                        vehicle_reg=reg if lob == "MOT" else None,
                        ncd=ncd,
                        renewal=renewal,
                    )
                    next_policy += 1
                    terms.append(term)
                    if self.chance(0.04):
                        cancel = self.date_between(start + DAY, min(expiry, AS_OF))
                        if cancel <= AS_OF:
                            term.cancelled_on = cancel
                            break
                    keep = {"MOT": 0.85, "HOM": 0.88, "TRV": 0.70}[lob]
                    if not self.chance(keep):
                        break
                    term.renewed = True
                    start, renewal = expiry + DAY, True
                    premium = cents(float(premium) * (1 + self.rng.normal(0.04, 0.05)))
                    if lob == "MOT":
                        ncd = min(9, (ncd or 0) + 1)
                    if broker and self.chance(0.03):
                        broker = self.pick(broker_codes)
        self._plant_policy_conditions(terms, people)
        return terms

    def _plant_policy_conditions(
        self, terms: list[Term], people: dict[int, dict[str, Any]]
    ) -> None:
        """
        Plant the policy edge cases that the legacy jobs' traps and bugs need.
        """
        by_index = list(range(len(terms)))
        # zero premiums (complimentary cover) and round premiums on band boundaries (SAS-12)
        for n, value in ((30, "0.00"), (30, "500.00"), (30, "1000.00"), (12, "250.00")):
            for i in self.rng.choice(by_index, size=n, replace=False):
                terms[int(i)].premium = Decimal(value)
        # a few policies starting on 29 Feb 2024 (BUG-02) and on 1 January or 31 December.
        # only a line's single term moves (never renewed, never cancelled), and only for a
        # customer who had joined by then, so no line overlaps itself and no cover predates
        # its customer
        starts = [dt.date(2024, 2, 29)] * 6 + [dt.date(2023, 12, 31), dt.date(2024, 1, 1)] * 3
        candidates = iter(
            t
            for t in terms
            if t.lob == "MOT"
            and not t.renewal
            and not t.renewed
            and t.cancelled_on is None
            and t.expiry < AS_OF
        )
        for start in starts:
            t = next(t for t in candidates if people[t.customer_id]["customer_since"] <= start)
            t.inception, t.expiry = start, add_months(start, 12) - DAY
        # mid-term adjustments: the premium changes part-way through the term
        for t in terms:
            if t.product_code == "TRV-SGL" or t.premium == 0:
                continue
            last_day = min(t.expiry, t.cancelled_on or t.expiry, AS_OF)
            if last_day - t.inception > dt.timedelta(days=60) and self.chance(0.08):
                t.mta_on = self.date_between(
                    t.inception + dt.timedelta(days=20), last_day - dt.timedelta(days=10)
                )
                t.mta_premium = cents(float(t.premium) * (1 + self.rng.normal(0.05, 0.12)))
        # keying variants that a case- and space-insensitive server hides (TSQL-01, TSQL-02)
        for t in terms:
            roll = self.rng.random()
            if roll < 0.025:
                t.status_variant = "title"
            elif roll < 0.035:
                t.status_variant = "pad"
            if self.chance(0.012):
                t.product_variant = self.pick(["lower", "pad"])
            if t.broker and self.chance(0.08):
                t.broker_variant = self.pick(["lower", "pad", "title"])
        # registrations: NULL in one snapshot and '' in the other (TSQL-06), or a real change
        mot = [t for t in terms if t.lob == "MOT"]
        for t in mot:
            t.reg_snap1 = t.reg_snap2 = t.vehicle_reg
        in_both = [t for t in mot if t.inception <= SNAPSHOT_DATES[0]]
        empties = self.rng.choice(len(in_both), size=150, replace=False)
        for k, i in enumerate(empties):
            t = in_both[int(i)]
            t.reg_snap1, t.reg_snap2 = (None, "") if k % 2 == 0 else ("", None)
        for t in in_both:
            if t.reg_snap1 and t.expiry >= SNAPSHOT_DATES[0] and self.chance(0.03):
                t.reg_snap2 = self._reg("Dublin", 2025)  # changed vehicle mid-term
        # up to 80 brokered policies change broker between the snapshots: real type-2 history
        for t in terms:
            t.broker_snap2 = t.broker
        movers = [t for t in in_both if t.broker and t.expiry >= SNAPSHOT_DATES[0]]
        for i in self.rng.choice(len(movers), size=min(80, len(movers)), replace=False):
            t = movers[int(i)]
            t.broker_snap2 = f"BRK{int(self.rng.integers(1, 41)):03d}"

    def _status(self, t: Term, on: dt.date) -> str:
        """
        Work out a term's status on a date, spelt in the term's sticky keying variant.

        A term past its expiry is EXPIRED when it was renewed and LAPSED when it wasn't.
        """
        if t.cancelled_on and t.cancelled_on <= on:
            status = "CANCELLED"
        elif t.expiry < on:
            status = "EXPIRED" if t.renewed else "LAPSED"
        else:
            status = "ACTIVE"
        if t.status_variant == "title":
            return status.title()
        if t.status_variant == "pad":
            return status + " "
        return status

    def policy_snapshots(self, terms: list[Term]) -> list[dict[str, Any]]:
        """
        Build the two policy snapshots: every term that had started by each snapshot date.

        The premium includes any mid-term adjustment made by then. In the second snapshot
        one term in 150 has its status flipped between capitals and title case, a change
        only a case-sensitive comparison sees (TSQL-01).

        Args:
            terms: Every policy term.

        Returns:
            The snapshot rows, first snapshot first.
        """
        rows = []
        case_flip = {t.policy_id for t in terms[::150]}
        for snap in SNAPSHOT_DATES:
            for t in terms:
                if t.inception > snap:
                    continue
                premium = t.premium
                if t.mta_on and t.mta_on <= snap:
                    premium = t.mta_premium
                status = self._status(t, snap)
                if snap == SNAPSHOT_DATES[1] and t.policy_id in case_flip:
                    status = status.title() if status.isupper() else status.upper()
                product = t.product_code
                if t.product_variant == "lower":
                    product = product.lower()
                elif t.product_variant == "pad":
                    product = product + " "
                broker = t.broker if snap == SNAPSHOT_DATES[0] else t.broker_snap2
                if broker and t.broker_variant == "lower":
                    broker = broker.lower()
                elif broker and t.broker_variant == "pad":
                    broker = broker + "  "
                elif broker and t.broker_variant == "title":
                    broker = broker.title()
                reg = t.reg_snap1 if snap == SNAPSHOT_DATES[0] else t.reg_snap2
                if t.lob != "MOT":
                    reg = None
                rows.append(
                    {
                        "snapshot_date": snap,
                        "policy_id": t.policy_id,
                        "policy_number": policy_number(t),
                        "customer_id": t.customer_id,
                        "product_code": product,
                        "broker_code": broker,
                        "inception_date": t.inception,
                        "expiry_date": t.expiry,
                        "status": status,
                        "cancellation_date": (
                            t.cancelled_on if t.cancelled_on and t.cancelled_on <= snap else None
                        ),
                        "annual_premium": premium,
                        "currency": t.currency,
                        "sum_insured": t.sum_insured,
                        "payment_frequency": t.frequency,
                        "vehicle_reg": reg,
                        "ncd_years": t.ncd,
                    }
                )
        return rows

    def premium_transactions(self, terms: list[Term]) -> list[dict[str, Any]]:
        """
        Build the premium transactions: NB or REN for every term, plus MTA and CAN rows.

        A term is booked up to 20 days before it starts. A mid-term adjustment books the
        premium change pro rata for the rest of the term, and a cancellation refunds the
        unearned premium as a negative amount.

        Args:
            terms: Every policy term.

        Returns:
            The transactions in booking order, with ``txn_id`` numbered in that order.
        """
        rows = []
        for t in terms:
            booked = t.inception - dt.timedelta(days=int(self.rng.integers(0, 21)))
            rows.append(
                {
                    "policy_id": t.policy_id,
                    "txn_type": "REN" if t.renewal else "NB",
                    "txn_date": booked,
                    "effective_from": t.inception,
                    "effective_to": t.expiry,
                    "amount": t.premium,
                    "currency": t.currency,
                }
            )
            term_days = (t.expiry - t.inception).days + 1
            if t.mta_on and t.mta_premium is not None:
                remaining = (t.expiry - t.mta_on).days + 1
                delta = (t.mta_premium - t.premium) * remaining / term_days
                rows.append(
                    {
                        "policy_id": t.policy_id,
                        "txn_type": "MTA",
                        "txn_date": t.mta_on,
                        "effective_from": t.mta_on,
                        "effective_to": t.expiry,
                        "amount": delta.quantize(Decimal("0.01")),
                        "currency": t.currency,
                    }
                )
            if t.cancelled_on:
                current = t.mta_premium if t.mta_on and t.mta_on <= t.cancelled_on else t.premium
                unearned = (t.expiry - t.cancelled_on).days + 1
                refund = -(current * unearned / term_days).quantize(Decimal("0.01"))
                rows.append(
                    {
                        "policy_id": t.policy_id,
                        "txn_type": "CAN",
                        "txn_date": t.cancelled_on,
                        "effective_from": t.cancelled_on,
                        "effective_to": t.expiry,
                        "amount": refund,
                        "currency": t.currency,
                    }
                )
        # sterling bookings moved into the four-day rate outage (26-29 February 2024, TSQL-09)
        near = [
            r
            for r in rows
            if r["currency"] == "GBP"
            and dt.date(2024, 2, 1) <= r["txn_date"] <= dt.date(2024, 3, 31)
        ]
        for r, day in zip(near[:12], [26, 27, 28, 29] * 3, strict=False):
            r["txn_date"] = dt.date(2024, 2, day)
            # new business and renewals are never booked after their cover starts
            if r["txn_type"] in ("NB", "REN") and r["effective_from"] < r["txn_date"]:
                r["txn_date"] = r["effective_from"]
        for r in rows:
            roll = self.rng.random()
            if roll < 0.005:
                r["txn_type"] = r["txn_type"].lower()
            elif roll < 0.009 and len(r["txn_type"]) < 4:
                r["txn_type"] = r["txn_type"] + " "
        rows.sort(key=lambda r: (r["txn_date"], r["policy_id"], r["txn_type"].upper()))
        for i, r in enumerate(rows, 1):
            r["txn_id"] = 7_000_000 + i
        return rows

    def fx_rates(self) -> list[dict[str, Any]]:
        """
        Build daily GBP and USD rates to EUR (source ``ECB``), as random walks from 2019.

        The first rate is for 2 January 2019. There is no rate at weekends, on six holidays
        (1 January, Good Friday, Easter Monday, 1 May, 25 and 26 December) or in an outage
        on 26-29 February 2024 (TSQL-09). Eight days also get a revised rate, with source
        ``ECB-REV``.

        Returns:
            The rate rows in extract order.
        """
        holidays: set[dt.date] = set()
        for year in range(2019, 2026):
            easter = _easter(year)
            holidays |= {
                dt.date(year, 1, 1),
                easter - 2 * DAY,
                easter + DAY,
                dt.date(year, 5, 1),
                dt.date(year, 12, 25),
                dt.date(year, 12, 26),
            }
        outage = {dt.date(2024, 2, d) for d in (26, 27, 28, 29)}
        level = {"GBP": 1.14, "USD": 0.89}
        rows = []
        day = dt.date(2019, 1, 1)
        while day <= AS_OF:
            if day.weekday() < 5 and day not in holidays and day not in outage:
                for ccy in ("GBP", "USD"):
                    level[ccy] *= float(np.exp(self.rng.normal(0, 0.004)))
                    rows.append(
                        {
                            "rate_date": day,
                            "currency": ccy,
                            "rate_to_eur": Decimal(f"{level[ccy]:.8f}"),
                            "source": "ECB",
                        }
                    )
            day += DAY
        revisions = []
        for i in self.rng.choice(len(rows), size=8, replace=False):
            r = dict(rows[int(i)])
            r["rate_to_eur"] = Decimal(f"{float(r['rate_to_eur']) * 1.0007:.8f}")
            r["source"] = "ECB-REV"
            revisions.append(r)
        revisions.sort(key=lambda r: (r["rate_date"], r["currency"]))
        return rows + revisions  # revisions arrive at the end of the extract

    ### Claims
    def claims(self, terms: list[Term]) -> list[dict[str, Any]]:
        """
        Build the claims register, with a Poisson number of claims per term.

        A loss is reported up to 400 days later, and dropped if not reported by the as-of
        date. Recent claims are more likely to be open. Status and line of business carry
        keying noise (TSQL-01, TSQL-02), and open claims more often have no handler
        (TSQL-05).

        Args:
            terms: Every policy term.

        Returns:
            The claims, numbered in reporting order. The private keys ``_open``,
            ``_closed_date``, ``_term`` and ``_no_pay`` are for :meth:`claim_financials`;
            :meth:`build` removes them.
        """
        claims: list[dict[str, Any]] = []
        handlers = [f"H{n:03d}" for n in range(101, 141)]
        for t in terms:
            end = min(t.expiry, (t.cancelled_on - DAY) if t.cancelled_on else t.expiry, AS_OF)
            if end < t.inception:
                continue
            years = ((end - t.inception).days + 1) / 365.0
            rate = CLAIM_FREQUENCY[t.lob]
            for _ in range(int(self.rng.poisson(rate * years))):
                loss = self.date_between(t.inception, end)
                delay = self.weighted([0, 1, 2, 3, 4], [12, 45, 30, 12, 1])
                delay_days = {
                    0: 0,
                    1: int(self.rng.integers(1, 8)),
                    2: int(self.rng.integers(8, 31)),
                    3: int(self.rng.integers(31, 121)),
                    4: int(self.rng.integers(121, 401)),
                }[delay]
                reported = loss + dt.timedelta(days=delay_days)
                if reported > AS_OF:
                    continue
                cause = self.pick(CAUSES[t.lob]) if not self.chance(0.03) else None
                claims.append(
                    {
                        "policy_id": t.policy_id,
                        "customer_id": t.customer_id,
                        "lob": t.lob,
                        "loss_date": loss,
                        "reported_date": reported,
                        "cause_code": cause,
                        "term": t,
                        "vehicle_reg": t.vehicle_reg,
                    }
                )
        self._plant_reporting_windows(claims, terms)
        claims.sort(key=lambda c: (c["reported_date"], c["policy_id"], c["loss_date"]))
        # recent claims that stay unpaid, aged exactly on an ageing-band boundary (BUG-04)
        recent = [
            c
            for c in claims
            if c["reported_date"] >= dt.date(2025, 9, 1) and c["term"].lob != "TRV"
        ]
        boundary = [30, 30, 30, 30, 29, 31, 60, 61, 30, 30, 59, 90]
        # spread over the recent claims; a small test population just gets fewer
        step = max(1, len(recent) // len(boundary))
        for c, days in zip(recent[::step], boundary, strict=False):
            c["reported_date"] = AS_OF - dt.timedelta(days=days)
            c["loss_date"] = min(c["loss_date"], c["reported_date"])
            c["no_pay"] = True
        claims.sort(key=lambda c: (c["reported_date"], c["policy_id"], c["loss_date"]))
        # a few claims keyed against the wrong line of business, such as a home claim on a
        # motor policy: the keying error T08's lob_mismatch_flag exists to catch
        wrong = {"MOT": "HOM", "HOM": "MOT", "TRV": "HOM"}
        for c in claims[50::450][:6]:
            c["lob"] = wrong[c["lob"]]
        # recent motor claims keyed in another case on a policy whose registration fails the
        # format rule: T08's motor test (lob_code = 'MOT') matches them only because the
        # server ignores case (TSQL-01)
        bad_reg = [
            c
            for c in claims
            if c["lob"] == "MOT"
            and c["reported_date"] > dt.date(2024, 12, 31)
            and c["vehicle_reg"]
            and not VALID_REG.match(c["vehicle_reg"])
        ]
        step = max(1, len(bad_reg) // 3)
        for c, keyed in zip(bad_reg[::step], ["mot", "Mot ", "Mot"], strict=False):
            c["keyed_lob"] = keyed
        rows = []
        for i, c in enumerate(claims, 1):
            claim_id = 300_000 + i
            age_years = (AS_OF - c["reported_date"]).days / 365.0
            p_open = (
                0.55
                if age_years < 1
                else 0.20
                if age_years < 2
                else 0.08
                if age_years < 3
                else 0.03
            )
            is_open = self.chance(p_open) or c.get("no_pay", False)
            reopened = not is_open and self.chance(0.03)
            closed_date = None
            if not is_open:
                closed_date = min(
                    AS_OF, c["reported_date"] + dt.timedelta(days=int(self.rng.integers(14, 600)))
                )
            status = "OPEN" if is_open else "REOPENED" if reopened else "CLOSED"
            roll = self.rng.random()
            if status == "OPEN":
                status = (
                    "Open"
                    if roll < 0.04
                    else "open"
                    if roll < 0.05
                    else "OPEN "
                    if roll < 0.07
                    else status
                )
            elif status == "CLOSED":
                status = "Closed" if roll < 0.03 else "CLOSED " if roll < 0.05 else status
            elif roll < 0.1:
                status = "Reopened"
            lob = c["lob"]
            roll = self.rng.random()  # drawn even when keyed_lob overrides it, to keep the stream
            if roll < 0.012:
                lob = lob.lower()
            elif roll < 0.022:
                lob = lob.title() + " "
            elif roll < 0.032:
                lob = lob + " "
            lob = c.get("keyed_lob", lob)
            handler = None
            if not self.chance(0.15 if status.strip().upper() == "OPEN" else 0.05):
                handler = self.pick(handlers)
            description = None
            if c["cause_code"] and not self.chance(0.1):
                reg = c["vehicle_reg"] if self.chance(0.5) else self._reg("Dublin", 2018)
                description = self.pick(DESCRIPTIONS[c["cause_code"]]).format(reg=reg)
            rows.append(
                {
                    "claim_id": claim_id,
                    "claim_number": f"CLM-{c['reported_date'].year}-{claim_id % 100_000:05d}",
                    "policy_id": c["policy_id"],
                    "customer_id": c["customer_id"],
                    "lob_code": lob,
                    "loss_date": c["loss_date"],
                    "reported_date": c["reported_date"],
                    "status": status,
                    "closed_date": closed_date,
                    "cause_code": c["cause_code"],
                    "handler_code": handler,
                    "description": description,
                    "_open": status.strip().upper() in ("OPEN", "REOPENED"),
                    "_closed_date": closed_date if not reopened else None,
                    "_term": c["term"],
                    "_no_pay": c.get("no_pay", False),
                }
            )
        return rows

    def _plant_reporting_windows(self, claims: list[dict[str, Any]], terms: list[Term]) -> None:
        """
        Plant 90 claims notified within 30 days after the policy's expiry date.

        These late notifications arm BUG-07, whose rule compares the report date with the
        policy's end date instead of its start.
        """
        ended = [
            t
            for t in terms
            if t.expiry < AS_OF - dt.timedelta(days=40)
            and not t.cancelled_on
            and t.product_code != "TRV-SGL"
        ]
        for i in self.rng.choice(len(ended), size=90, replace=False):
            t = ended[int(i)]
            loss = t.expiry - dt.timedelta(days=int(self.rng.integers(0, 20)))
            reported = t.expiry + dt.timedelta(days=int(self.rng.integers(0, 31)))
            claims.append(
                {
                    "policy_id": t.policy_id,
                    "customer_id": t.customer_id,
                    "lob": t.lob,
                    "loss_date": loss,
                    "reported_date": reported,
                    "cause_code": self.pick(CAUSES[t.lob]),
                    "term": t,
                    "vehicle_reg": t.vehicle_reg,
                }
            )

    def claim_financials(
        self,
        claims: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Build the payments and reserves of every claim.

        Payments share out a log-normal expected cost that depends on the cause. Reserves
        start at the report date, are revised a few times and drop to zero at closure.
        Planted along the way: nil claims, motor recoveries as negative amounts, missing and
        zero amounts (BUG-08), first payments on the loss date (BUG-05), rows dated after the
        as-of date, orphan payments (SAS-05) and same-day reserve corrections.

        Args:
            claims: Claims from :meth:`claims`, still with their private keys.

        Returns:
            The payments and the reserves, which :meth:`build` numbers.
        """
        payments: list[dict[str, Any]] = []
        reserves: list[dict[str, Any]] = []
        for c in claims:
            cause = c["cause_code"] or "ACC"
            severity = {
                "COLL": 3200,
                "THEFT": 6500,
                "GLASS": 450,
                "FIRE": 9000,
                "INJ": 18000,
                "ESCAPE": 5200,
                "STORM": 3800,
                "FLOOD": 12000,
                "ACC": 900,
                "MEDIC": 2600,
                "BAGG": 700,
                "CANX": 1500,
            }[cause]
            expected = self.lognormal(severity, 0.7)
            last = c["_closed_date"] or AS_OF
            nil_claim = (not c["_open"] and self.chance(0.15)) or c["_no_pay"]
            n_pay = (
                0
                if nil_claim
                else int(self.rng.integers(0 if c["_open"] else 1, 6 if c["_open"] else 9))
            )
            day0 = c["reported_date"] == c["loss_date"] and self.chance(0.6)
            for k in range(n_pay):
                if k == 0 and day0:
                    pay_date = c["loss_date"]
                else:
                    pay_date = self.date_between(c["reported_date"], last)
                share = expected / max(n_pay, 1) * float(self.rng.uniform(0.4, 1.6))
                ptype = "INDEMNITY" if self.chance(0.78) else "EXPENSE"
                amount: Decimal | None = cents(share if ptype == "INDEMNITY" else share * 0.15)
                roll = self.rng.random()
                if roll < 0.008:
                    amount = None  # not keyed yet
                elif roll < 0.013:
                    amount = Decimal("0.00")
                payments.append(
                    {
                        "claim_id": c["claim_id"],
                        "payment_date": pay_date,
                        "amount": amount,
                        "payment_type": ptype,
                        "payee_type": None if self.chance(0.05) else self.pick(PAYEES),
                    }
                )
            # a recovery is a negative payment; BUG-08 counts missing amounts as recoveries too
            if (
                not c["_open"]
                and n_pay
                and c["lob_code"].strip().upper() == "MOT"
                and self.chance(0.12)
            ):
                payments.append(
                    {
                        "claim_id": c["claim_id"],
                        "payment_date": self.date_between(c["reported_date"], last),
                        "amount": -cents(expected * float(self.rng.uniform(0.05, 0.4))),
                        "payment_type": "RECOVERY",
                        "payee_type": None,
                    }
                )
            if c["_open"] and not c["_no_pay"] and self.chance(0.03):
                payments.append(
                    {
                        "claim_id": c["claim_id"],
                        "payment_date": AS_OF + dt.timedelta(days=int(self.rng.integers(1, 40))),
                        "amount": cents(expected * 0.2),
                        "payment_type": "INDEMNITY",
                        "payee_type": "CLAIMANT",
                    }
                )
            # reserves: an initial estimate per type, revisions, zero at closure
            types = ["INDEMNITY"] + (["EXPENSE"] if self.chance(0.4) else [])
            for rtype in types:
                amount = expected if rtype == "INDEMNITY" else expected * 0.12
                reserves.append(
                    {
                        "claim_id": c["claim_id"],
                        "reserve_date": c["reported_date"],
                        "reserve_type": rtype,
                        "reserve_amount": cents(amount),
                    }
                )
                for _ in range(int(self.rng.integers(0, 5))):
                    amount = max(0.0, amount * float(self.rng.uniform(0.6, 1.5)))
                    reserves.append(
                        {
                            "claim_id": c["claim_id"],
                            "reserve_date": self.date_between(c["reported_date"], last),
                            "reserve_type": rtype,
                            "reserve_amount": cents(amount),
                        }
                    )
                if c["_closed_date"]:
                    reserves.append(
                        {
                            "claim_id": c["claim_id"],
                            "reserve_date": last,
                            "reserve_type": rtype,
                            "reserve_amount": Decimal("0.00"),
                        }
                    )
                elif c["_open"] and self.chance(0.02):
                    reserves.append(
                        {
                            "claim_id": c["claim_id"],
                            "reserve_date": AS_OF
                            + dt.timedelta(days=int(self.rng.integers(1, 30))),
                            "reserve_type": rtype,
                            "reserve_amount": cents(amount * 1.1),
                        }
                    )
        self._plant_last_activity(claims, payments)
        self._plant_payment_noise(payments)
        # orphan payments: the claim was purged from the register (SAS-05)
        for k in range(25):
            payments.append(
                {
                    "claim_id": 399_000 + k,
                    "payment_date": self.date_between(dt.date(2020, 1, 1), AS_OF),
                    "amount": cents(self.lognormal(800, 0.5)),
                    "payment_type": "INDEMNITY",
                    "payee_type": "CLAIMANT",
                }
            )
        # same-day reserve corrections: two rows for one claim, type and date
        for i in self.rng.choice(len(reserves), size=60, replace=False):
            r = dict(reserves[int(i)])
            r["reserve_amount"] = cents(float(r["reserve_amount"]) * 1.05 + 10)
            reserves.append(r)
        return payments, reserves

    def _plant_last_activity(
        self, claims: list[dict[str, Any]], payments: list[dict[str, Any]]
    ) -> None:
        """
        Plant open claims whose last activity sits exactly on an ageing-band boundary.

        Thirty-two open claims with payments have them moved so that the last one falls 29,
        30, 31, 60 or 61 days before the as-of date. Half land on exactly 30 days, the age
        that BUG-04's bands leave out.
        """
        by_claim: dict[int, list[dict[str, Any]]] = {}
        for p in payments:
            by_claim.setdefault(p["claim_id"], []).append(p)
        open_paid = [
            c
            for c in claims
            if c["_open"]
            and c["claim_id"] in by_claim
            and c["reported_date"] <= dt.date(2025, 10, 1)
        ]
        boundary_days = [30] * 4 + [29, 31, 60, 61]
        chosen = self.rng.choice(len(open_paid), size=8 * len(boundary_days) // 2, replace=False)
        for k, i in enumerate(chosen):
            c = open_paid[int(i)]
            last = AS_OF - dt.timedelta(days=boundary_days[k % len(boundary_days)])
            pays = [p for p in by_claim[c["claim_id"]] if p["payment_date"] <= AS_OF]
            for p in pays:
                if p["payment_date"] > last:
                    p["payment_date"] = self.date_between(c["reported_date"], last)
            pays.sort(key=lambda p: p["payment_date"])
            if pays:
                pays[-1]["payment_date"] = last
                if pays[-1]["amount"] is None:
                    pays[-1]["amount"] = Decimal("125.00")

    def _plant_payment_noise(self, payments: list[dict[str, Any]]) -> None:
        """
        Add keying noise to payment types: 2% in title case and 1% with a trailing space.
        """
        for p in payments:
            roll = self.rng.random()
            if roll < 0.02:
                p["payment_type"] = p["payment_type"].title()
            elif roll < 0.03:
                p["payment_type"] = p["payment_type"] + " "

    ### Assembly
    def build(self) -> dict[str, list[dict[str, Any]]]:
        """
        Generate every source table, in the fixed order that keeps the output deterministic.

        Rows are put in extract order, payments and reserves are numbered, and every table
        gets a dense ``_row_seq`` from 1. Payments are in the order they were keyed: about 5%
        are keyed up to 20 days after the payment date, so extract order differs from
        payment-date order (SAS-06).

        Returns:
            The rows of each table, by bare table name such as ``claims``.
        """
        products = self.products()
        brokers = self.brokers()
        customers, people = self.customers()
        terms = self.policies(people, brokers)
        snapshots = self.policy_snapshots(terms)
        txns = self.premium_transactions(terms)
        fx = self.fx_rates()
        claims = self.claims(terms)
        payments, reserves = self.claim_financials(claims)

        # extract order (_row_seq) and identifiers
        products.sort(key=lambda r: r["product_code"])
        brokers.sort(key=lambda r: r["broker_code"])
        snapshots.sort(key=lambda r: (r["snapshot_date"], r["policy_id"]))
        for p in payments:
            lag = int(self.rng.integers(1, 21)) if self.chance(0.05) else 0
            p["_keyed"] = p["payment_date"] + dt.timedelta(days=lag)
        payments.sort(key=lambda p: (p["_keyed"], p["claim_id"]))
        for i, p in enumerate(payments, 1):
            p["payment_id"] = 800_000 + i
        reserves.sort(key=lambda r: (r["reserve_date"], r["claim_id"], r["reserve_type"]))
        for i, r in enumerate(reserves, 1):
            r["reserve_id"] = 900_000 + i
        for c in claims:
            for key in ("_open", "_closed_date", "_term", "_no_pay"):
                c.pop(key)
        for p in payments:
            p.pop("_keyed")
        tables = {
            "customers": customers,
            "brokers": brokers,
            "products": products,
            "policy_snapshots": snapshots,
            "premium_transactions": txns,
            "claims": claims,
            "claim_payments": payments,
            "claim_reserves": reserves,
            "fx_rates": fx,
        }
        for rows in tables.values():
            for i, row in enumerate(rows, 1):
                row["_row_seq"] = i
        return tables


### Schemas, files and the manifest

_ARROW = {
    "int": pa.int32(),
    "bigint": pa.int64(),
    "smallint": pa.int16(),
    "boolean": pa.bool_(),
    "double": pa.float64(),
    "string": pa.string(),
    "date": pa.date32(),
    "timestamp_ntz": pa.timestamp("us"),
}
"""The Arrow type of each logical type in the data dictionary, apart from decimals."""


def arrow_type(logical: str) -> pa.DataType:
    """
    Map a logical type from the data dictionary to its Arrow type.

    Args:
        logical: A logical type, such as ``int``, ``decimal(12,2)`` or ``timestamp_ntz``.

    Returns:
        The Arrow type.

    Raises:
        KeyError: The type is not one the dictionary uses.
    """
    if logical.startswith("decimal("):
        p, s = (int(x) for x in logical[8:-1].split(","))
        return pa.decimal128(p, s)
    return _ARROW[logical]


def load_dictionary(path: Path = DICTIONARY_PATH) -> list[TableSchema]:
    """
    Load the data dictionary: the schema of every source extract.

    Args:
        path: The dictionary's YAML file.

    Returns:
        One schema per ``stg`` table, in dictionary order.
    """
    data = parse_yaml(path.read_text(encoding="utf-8"))
    return [TableSchema.model_validate(t) for t in data["tables"]]


def to_arrow(schema: TableSchema, rows: list[dict[str, Any]]) -> pa.Table:
    """
    Build a typed Arrow table in dictionary column order, checking nullability.

    Args:
        schema: The table's entry in the data dictionary.
        rows: The generated rows, keyed by column name.

    Returns:
        The typed table.

    Raises:
        ValueError: A NOT NULL column holds a NULL, or a row has a column the dictionary
            doesn't declare.
    """
    fields, arrays = [], []
    for col in schema.columns:
        values = [r.get(col.name) for r in rows]
        if not col.nullable and any(v is None for v in values):
            raise ValueError(f"{schema.name}.{col.name} has NULLs but is NOT NULL")
        typ = arrow_type(col.data_type)
        if pa.types.is_decimal(typ):
            # arithmetic can yield Decimal('-0.00'), but SQL Server stores plain zero
            values = [v.copy_abs() if v is not None and v == 0 else v for v in values]
        fields.append(pa.field(col.name, typ, nullable=col.nullable))
        arrays.append(pa.array(values, type=typ))
    extra = set().union(*(r.keys() for r in rows)) - {c.name for c in schema.columns}
    if extra:
        raise ValueError(f"{schema.name} rows have undeclared columns {sorted(extra)}")
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def check_lengths(schema: TableSchema, table: pa.Table) -> None:
    """
    Refuse values longer than the legacy column (SQL Server would reject the load).

    Only CHAR, VARCHAR, NCHAR and NVARCHAR columns are checked, and lengths count
    characters.

    Args:
        schema: The table's entry in the data dictionary.
        table: The typed table.

    Raises:
        ValueError: A value is longer than its column's width.
    """
    for col in schema.columns:
        if col.legacy_type and "CHAR(" in col.legacy_type.upper():
            size = col.legacy_type.split("(")[1].rstrip(")")
            if size.upper() == "MAX":
                continue  # (N)VARCHAR(MAX) has no width to exceed
            width = int(size)
            longest = max((len(v) for v in table.column(col.name).to_pylist() if v), default=0)
            if longest > width:
                raise ValueError(f"{schema.name}.{col.name}: value of {longest} > {width}")


def generate(seed: int = SEED, n_customers: int = N_CUSTOMERS) -> dict[str, pa.Table]:
    """
    Generate every source table as typed Arrow tables keyed by bare table name.

    Args:
        seed: The seed; the committed extracts use :data:`SEED`.
        n_customers: How many customers to generate; fewer give a smaller, quicker estate.

    Returns:
        A table per bare table name, such as ``claims``, in dictionary order.

    Raises:
        ValueError: A table breaks its dictionary entry: a NULL in a NOT NULL column, an
            undeclared column or an over-long value.
    """
    rows = SynthInsure(seed=seed, n_customers=n_customers).build()
    tables = {}
    for schema in load_dictionary():
        name = schema.name.split(".", 1)[1]
        table = to_arrow(schema, rows[name])
        check_lengths(schema, table)
        tables[name] = table
    return tables


def write(
    tables: dict[str, pa.Table], out_dir: Path = DATA_DIR, seed: int = SEED, csv: bool = True
) -> list[TableFingerprint]:
    """
    Write Parquet (committed), CSV (gitignored) and ``manifest.json``.

    Args:
        tables: Tables from :func:`generate`, by bare table name.
        out_dir: Folder for the Parquet files and the manifest; CSV copies go in ``csv/``.
        seed: Seed to record in the manifest: the one the tables were generated with.
        csv: Also write the CSV copies.

    Returns:
        A fingerprint per table, as recorded in the manifest.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprints = []
    for name, table in tables.items():
        path = out_dir / f"{name}.parquet"
        pq.write_table(table, path, compression="zstd", write_statistics=True)
        if csv:
            (out_dir / "csv").mkdir(exist_ok=True)
            pacsv.write_csv(table, out_dir / "csv" / f"{name}.csv")
        rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path.name
        fingerprints.append(
            TableFingerprint(
                table=f"stg.{name}",
                path=str(rel),
                rows=table.num_rows,
                file_sha256=file_sha256(path),
                content_sha256=content_sha256(table),
            )
        )
    manifest = {
        "generator": "lansh.estate.generate",
        "lansh_version": __version__,
        "seed": seed,
        "as_of_date": AS_OF.isoformat(),
        "synthetic": True,
        "tables": [f.model_dump() for f in fingerprints],
        "total_rows": sum(f.rows for f in fingerprints),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return fingerprints


def read_tables(data_dir: Path = DATA_DIR) -> dict[str, pa.Table]:
    """
    Read the committed Parquet extracts, keyed by bare table name.

    Args:
        data_dir: Folder holding the extracts and their ``dictionary.yaml``.

    Returns:
        A table per bare table name, in dictionary order.
    """
    names = [s.name.split(".", 1)[1] for s in load_dictionary(data_dir / "dictionary.yaml")]
    return {name: pq.read_table(data_dir / f"{name}.parquet") for name in names}
