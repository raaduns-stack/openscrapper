import asyncio

from src.extract.adaptive import AdaptiveLeadExtractor


def test_labeled_plain_text_contact_with_email():
    html = """
    <html><body>
    <h1>Molybdenum Mines Nigeria Ltd</h1>
    <p>Management</p>
    <p>Managing Director: Khalil Yassin</p>
    <p>Director: James Ireland</p>
    <p>Email: jamesireland55@gmail.com</p>
    </body></html>
    """
    leads = asyncio.run(
        AdaptiveLeadExtractor().extract(html, "https://example.test/management")
    )
    assert len(leads) == 1
    assert leads[0].first_name == "James"
    assert leads[0].last_name == "Ireland"
    assert leads[0].position == "Director"
    assert str(leads[0].email) == "jamesireland55@gmail.com"
