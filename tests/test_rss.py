from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from dhd_digest.ingest.rss import load_feeds, parse_feed


def rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate>"
        f"<description><![CDATA[<p>{s}</p>]]></description></item>"
        for t, l, d, s in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


def test_parses_feed_items_into_candidate_links():
    now = format_datetime(datetime.now(timezone.utc))
    old = format_datetime(datetime.now(timezone.utc) - timedelta(days=200))
    out = parse_feed(rss(
        ("Neon Buys ‘Sentimental Value’ Follow-Up Out Of TIFF", "https://deadline.com/2026/09/neon-buys-x-1236/",
         now, "Neon has acquired <b>North American rights</b> to the drama."),
        ("An old piece", "https://deadline.com/2026/03/old-1235/", old, "stale"),
        ("‘Dune: Part Three’ Review: Villeneuve Sticks The Landing", "https://deadline.com/2026/09/r/", now, "x"),
        ("Venice Red Carpet Photos", "https://deadline.com/2026/09/p/", now, "x"),
    ), "Deadline")
    assert len(out) == 1
    it = out[0]
    assert it["raw_url"] == "https://deadline.com/2026/09/neon-buys-x-1236/"
    assert it["anchor_text"].startswith("Neon Buys")
    assert it["context"] == "Neon has acquired North American rights to the drama."
    assert it["source"] == "Deadline"


def test_feed_list_is_well_formed():
    feeds = load_feeds()
    names = {f["name"] for f in feeds}
    assert {"Deadline Film", "Variety Film", "THR Movies"} <= names
    assert all(f["url"].startswith("https://") for f in feeds)


def test_pages_back_until_older_items():
    from dhd_digest.ingest.rss import fetch_feed, page_url

    assert page_url("https://deadline.com/v/film/feed/", 1) == "https://deadline.com/v/film/feed/"
    assert page_url("https://deadline.com/v/film/feed/", 3) == "https://deadline.com/v/film/feed/?paged=3"

    def day(n):
        return format_datetime(datetime.now(timezone.utc) - timedelta(days=n))

    pages = {1: rss(("A", "https://d.com/a", day(0), ""), ("B", "https://d.com/b", day(1), "")),
             2: rss(("C", "https://d.com/c", day(1), ""), ("D", "https://d.com/d", day(3), "")),
             3: rss(("E", "https://d.com/e", day(4), ""))}

    class Resp:
        def __init__(self, page):
            self.status_code = 200 if page in pages else 404
            self.content = pages.get(page, b"")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url):
            page = int(url.split("paged=")[1]) if "paged=" in url else 1
            self.calls.append(page)
            return Resp(page)

    c = Client()
    out = fetch_feed(c, {"name": "Deadline Film", "url": "https://d.com/feed/"})
    assert [i["anchor_text"] for i in out] == ["A", "B", "C", "D"]   # page 2 reached day 3: stop
    assert c.calls == [1, 2]

    pages.pop(2)                                                      # feed that ends early
    c = Client()
    assert [i["anchor_text"] for i in fetch_feed(c, {"name": "x", "url": "https://d.com/feed/"})] == ["A", "B"]
    assert c.calls == [1, 2]
