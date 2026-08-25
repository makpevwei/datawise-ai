"""Deterministic country name/code -> centroid lookup.

Tableau-style "country" geographic role: resolves a country column's raw
text values to a representative (lat, lng) point for country-level
mapping. Coordinates are approximate geographic centroids -- they
represent "somewhere inside this country", not any individual
transaction's real location, and the map UI must say so explicitly
(Phase 4 continuation section 22).

This is a static, hand-maintained table -- no external geocoding API is
called, so lookups are instant and offline, and nothing is ever
fabricated: a value that isn't in this table is reported as unmatched,
never assigned a guessed coordinate.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CountryRecord:
    name: str
    iso2: str
    iso3: str
    lat: float
    lng: float


# (canonical name, ISO-2, ISO-3, lat, lng, [extra name aliases])
_COUNTRIES: list[tuple[str, str, str, float, float, list[str]]] = [
    ("Nigeria", "NG", "NGA", 9.08, 8.68, ["federal republic of nigeria"]),
    ("Ghana", "GH", "GHA", 7.95, -1.02, []),
    ("Kenya", "KE", "KEN", -0.02, 37.91, []),
    ("South Africa", "ZA", "ZAF", -30.56, 22.94, []),
    ("Egypt", "EG", "EGY", 26.82, 30.80, []),
    ("Ethiopia", "ET", "ETH", 9.15, 40.49, []),
    ("Morocco", "MA", "MAR", 31.79, -7.09, []),
    ("Algeria", "DZ", "DZA", 28.03, 1.66, []),
    ("Tunisia", "TN", "TUN", 33.89, 9.54, []),
    ("Uganda", "UG", "UGA", 1.37, 32.29, []),
    ("Tanzania", "TZ", "TZA", -6.37, 34.89, []),
    ("Rwanda", "RW", "RWA", -1.94, 29.87, []),
    ("Senegal", "SN", "SEN", 14.50, -14.45, []),
    ("Ivory Coast", "CI", "CIV", 7.54, -5.55, ["cote d'ivoire", "cote divoire"]),
    ("Cameroon", "CM", "CMR", 7.37, 12.35, []),
    ("Zambia", "ZM", "ZMB", -13.13, 27.85, []),
    ("Zimbabwe", "ZW", "ZWE", -19.02, 29.15, []),
    ("Angola", "AO", "AGO", -11.20, 17.87, []),
    ("Mozambique", "MZ", "MOZ", -18.67, 35.53, []),
    ("United States", "US", "USA", 39.83, -98.58, ["usa", "united states of america", "us", "america"]),
    ("Canada", "CA", "CAN", 56.13, -106.35, []),
    ("Mexico", "MX", "MEX", 23.63, -102.55, []),
    ("Brazil", "BR", "BRA", -14.24, -51.93, []),
    ("Argentina", "AR", "ARG", -38.42, -63.62, []),
    ("Chile", "CL", "CHL", -35.68, -71.54, []),
    ("Colombia", "CO", "COL", 4.57, -74.30, []),
    ("Peru", "PE", "PER", -9.19, -75.02, []),
    ("United Kingdom", "GB", "GBR", 55.38, -3.44, ["uk", "great britain", "britain", "england"]),
    ("Ireland", "IE", "IRL", 53.41, -8.24, []),
    ("France", "FR", "FRA", 46.23, 2.21, []),
    ("Germany", "DE", "DEU", 51.17, 10.45, []),
    ("Spain", "ES", "ESP", 40.46, -3.75, []),
    ("Portugal", "PT", "PRT", 39.40, -8.22, []),
    ("Italy", "IT", "ITA", 41.87, 12.57, []),
    ("Netherlands", "NL", "NLD", 52.13, 5.29, ["holland"]),
    ("Belgium", "BE", "BEL", 50.50, 4.47, []),
    ("Switzerland", "CH", "CHE", 46.82, 8.23, []),
    ("Austria", "AT", "AUT", 47.52, 14.55, []),
    ("Sweden", "SE", "SWE", 60.13, 18.64, []),
    ("Norway", "NO", "NOR", 60.47, 8.47, []),
    ("Denmark", "DK", "DNK", 56.26, 9.50, []),
    ("Finland", "FI", "FIN", 61.92, 25.75, []),
    ("Poland", "PL", "POL", 51.92, 19.15, []),
    ("Ukraine", "UA", "UKR", 48.38, 31.17, []),
    ("Russia", "RU", "RUS", 61.52, 105.32, ["russian federation"]),
    ("Greece", "GR", "GRC", 39.07, 21.82, []),
    ("Turkey", "TR", "TUR", 38.96, 35.24, ["turkiye"]),
    ("Czech Republic", "CZ", "CZE", 49.82, 15.47, ["czechia"]),
    ("Romania", "RO", "ROU", 45.94, 24.97, []),
    ("Hungary", "HU", "HUN", 47.16, 19.50, []),
    ("China", "CN", "CHN", 35.86, 104.20, ["people's republic of china", "prc"]),
    ("Japan", "JP", "JPN", 36.20, 138.25, []),
    ("South Korea", "KR", "KOR", 35.91, 127.77, ["korea, republic of", "republic of korea"]),
    ("India", "IN", "IND", 20.59, 78.96, []),
    ("Pakistan", "PK", "PAK", 30.38, 69.35, []),
    ("Bangladesh", "BD", "BGD", 23.68, 90.36, []),
    ("Indonesia", "ID", "IDN", -0.79, 113.92, []),
    ("Malaysia", "MY", "MYS", 4.21, 101.98, []),
    ("Singapore", "SG", "SGP", 1.35, 103.82, []),
    ("Thailand", "TH", "THA", 15.87, 100.99, []),
    ("Vietnam", "VN", "VNM", 14.06, 108.28, []),
    ("Philippines", "PH", "PHL", 12.88, 121.77, []),
    ("Saudi Arabia", "SA", "SAU", 23.89, 45.08, []),
    ("United Arab Emirates", "AE", "ARE", 23.42, 53.85, ["uae"]),
    ("Qatar", "QA", "QAT", 25.35, 51.18, []),
    ("Israel", "IL", "ISR", 31.05, 34.85, []),
    ("Iran", "IR", "IRN", 32.43, 53.69, []),
    ("Iraq", "IQ", "IRQ", 33.22, 43.68, []),
    ("Jordan", "JO", "JOR", 30.59, 36.24, []),
    ("Lebanon", "LB", "LBN", 33.85, 35.86, []),
    ("Australia", "AU", "AUS", -25.27, 133.78, []),
    ("New Zealand", "NZ", "NZL", -40.90, 174.89, []),
    ("Netherlands Antilles", "AN", "ANT", 12.23, -68.99, []),
]

_ALIAS_TO_RECORD: dict[str, CountryRecord] = {}


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().replace(".", "").replace("_", " ").split())


for _name, _iso2, _iso3, _lat, _lng, _aliases in _COUNTRIES:
    record = CountryRecord(name=_name, iso2=_iso2, iso3=_iso3, lat=_lat, lng=_lng)
    for key in [_name, _iso2, _iso3, *_aliases]:
        _ALIAS_TO_RECORD[_normalize(key)] = record


def resolve_country(raw_value: str) -> CountryRecord | None:
    """Deterministic lookup only -- never guesses. Returns None (unmatched)
    for anything not in the table above, rather than inventing coordinates."""
    if not raw_value or not isinstance(raw_value, str):
        return None
    return _ALIAS_TO_RECORD.get(_normalize(raw_value))


COUNTRY_COLUMN_NAME_ALIASES = {
    "country", "country name", "countryname", "nation", "country code",
    "countrycode", "iso country", "iso country code", "isocountry", "isocountrycode",
    "country_name", "country_code", "iso_country", "iso_country_code",
}


def looks_like_country_column(column_name: str) -> bool:
    normalized = _normalize(column_name)
    return normalized in COUNTRY_COLUMN_NAME_ALIASES
