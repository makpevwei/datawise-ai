from app.geography.countries import looks_like_country_column, resolve_country


def test_resolves_canonical_names():
    nigeria = resolve_country("Nigeria")
    assert nigeria is not None
    assert nigeria.iso2 == "NG"
    assert nigeria.iso3 == "NGA"


def test_resolves_common_aliases_and_iso_codes():
    for value in ["USA", "US", "United States of America", "united states"]:
        country = resolve_country(value)
        assert country is not None, value
        assert country.iso2 == "US"

    for value in ["UK", "United Kingdom", "Great Britain", "GB", "GBR"]:
        country = resolve_country(value)
        assert country is not None, value
        assert country.iso2 == "GB"

    for value in ["UAE", "United Arab Emirates"]:
        country = resolve_country(value)
        assert country is not None, value
        assert country.iso2 == "AE"


def test_resolution_is_case_and_whitespace_insensitive():
    assert resolve_country("  nigeria  ") is not None
    assert resolve_country("NIGERIA") is not None
    assert resolve_country("NiGeRiA") is not None


def test_never_fabricates_a_coordinate_for_an_unmatched_value():
    assert resolve_country("Wakanda") is None
    assert resolve_country("") is None
    assert resolve_country("asdkjaslkdj") is None


def test_country_column_name_detection():
    for name in ["country", "Country", "country_name", "Country Name", "nation", "country_code", "iso_country", "ISO Country Code"]:
        assert looks_like_country_column(name), name
    for name in ["region", "state", "city", "customer_id", "revenue"]:
        assert not looks_like_country_column(name), name
