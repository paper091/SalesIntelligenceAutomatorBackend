from app.models.schemas import PageContent
from app.pipeline.extractor import extract_content

HOMEPAGE_HTML = """
<html><body>
<nav>Home | About | Services | Contact</nav>
<main>
<h1>Acme Roofing</h1>
<p>We provide residential and commercial roofing services across Dallas, Texas.
Our team has over twenty years of experience installing and repairing roofs for
homeowners and businesses alike.</p>
</main>
<footer>Copyright 2024 Acme Roofing. All rights reserved. Privacy Policy.</footer>
</body></html>
"""

ABOUT_HTML = """
<html><body>
<nav>Home | About | Services | Contact</nav>
<main>
<h1>About Acme Roofing</h1>
<p>Founded in 2001, Acme Roofing has grown into the leading roofing contractor in
the Dallas-Fort Worth metro area, serving thousands of satisfied customers with
quality materials and expert craftsmanship.</p>
</main>
<footer>Copyright 2024 Acme Roofing. All rights reserved. Privacy Policy.</footer>
</body></html>
"""


def test_extract_content_drops_repeated_boilerplate():
    pages = [
        PageContent(url="https://acme.com/", html=HOMEPAGE_HTML),
        PageContent(url="https://acme.com/about", html=ABOUT_HTML),
    ]

    result = extract_content(pages)

    assert "Copyright 2024" not in result.text
    assert "Privacy Policy" not in result.text
    assert "Acme Roofing" in result.text
    assert not result.thin_content


def test_extract_content_flags_thin_content():
    pages = [PageContent(url="https://acme.com/", html="<html><body></body></html>")]
    result = extract_content(pages)
    assert result.thin_content is True
    assert result.text == ""
