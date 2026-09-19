from src.extract.evidence import EvidenceBuilder


def test_evidence_preserves_page_and_extracts_email():
    page = EvidenceBuilder().build(
        url="https://example.com/companies",
        html="""
        <html>
          <body>
            <h1>ABC Mining</h1>
            <p>Contact JOHN@ABC.COM</p>
          </body>
        </html>
        """,
    )

    assert page.usable
    assert "ABC Mining" in page.content
    assert any(
        field.field == "email"
        and field.value == "john@abc.com"
        for field in page.fields
    )


def test_evidence_preserves_rendering_source():
    page = EvidenceBuilder().build(
        url="https://example.com",
        html="<body>Rendered</body>",
        rendered=True,
        source="scrapy-playwright",
    )

    assert page.rendered is True
    assert page.source == "scrapy-playwright"
