from app.pipeline.intake import parse_leads


def test_url_vs_name_detection():
    leads = parse_leads("https://www.example.com\nAcme Roofing - Dallas TX")
    assert leads[0].url == "https://www.example.com"
    assert leads[0].name is None

    assert leads[1].url is None
    assert leads[1].name == "Acme Roofing"
    assert leads[1].location_hint == "Dallas TX"


def test_url_normalization_adds_scheme_and_lowercases_host():
    leads = parse_leads("WWW.Example.COM/Path")
    assert leads[0].url == "https://www.example.com/Path"


def test_dedupe_and_blank_lines():
    leads = parse_leads("https://www.example.com\n\nhttps://www.example.com\n  \n")
    assert len(leads) == 1


def test_name_without_location():
    leads = parse_leads("Joe's Bakery")
    assert leads[0].name == "Joe's Bakery"
    assert leads[0].location_hint is None
