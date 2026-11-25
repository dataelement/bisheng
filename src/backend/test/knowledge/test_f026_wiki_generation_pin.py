import pytest

from test.knowledge.test_f026_govern import WikiPort, wiki_client


@pytest.mark.parametrize("route", ["graph", "search?q=topic"])
async def test_displayed_generation_pins_graph_and_search_before_content_read(route):
    port = WikiPort()
    sep = "&" if "?" in route else "?"
    async with wiki_client(port) as client:
        result = await client.get(f"/11/wiki/{route}{sep}generation=1")
    assert result.json()["status_code"] == 18089
    assert not port.calls
