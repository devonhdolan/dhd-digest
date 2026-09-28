from dhd_digest.ingest.normalize import canonicalize


def test_strips_tracking_params():
    u = ("https://www.techcrunch.com/2022/12/05/twelve-labs/?utm_source=x"
         "&utm_campaign=y&ck_subscriber_id=1")
    assert canonicalize(u) == "https://techcrunch.com/2022/12/05/twelve-labs"


def test_keeps_meaningful_params():
    assert "v=abc123" in canonicalize("https://www.youtube.com/watch?v=abc123&utm_source=n")


def test_rejects_junk():
    assert canonicalize("https://list-manage.com/unsubscribe?u=1") is None
    assert canonicalize("https://twitter.com/intent/tweet?text=hi") is None


def test_dedups_www_and_slash():
    a = canonicalize("https://www.variety.com/2022/film/news/x/")
    b = canonicalize("http://variety.com/2022/film/news/x")
    assert a == b


# Real links from the issue 251 draft that slipped through as trackers.
ELINK = ("https://elink22c.strictlyvc.com/ss/c/u001.dcUtNT9M06sDMhLsmBmtzWMHc/4ud/"
         "L-FsBhnYTkGyqMK5U6YPAA/h28/h001.paQ5TYaSWKqiIFezhPFAOLrFJL1y2BLLfyDJVXAE6LA")
GHOST = "https://spyglass.org/r/1af18231?m=236ae5c1-6237-4215-90ea-5fefd025a888"
PUCK = ("https://email.puck.news/e/c/eyJlbWFpbF9pZCI6ImRnVDJ4Z1lEQU5DQ0FjLUNBUUdnMXNJSXZq"
        "eEMyRHU2U1pKbTR2UT0iLCJocmVmIjoiaHR0cHM6Ly9oYnIub3JnLzIwMjYvMDkvYm9iLWlnZXItb24t"
        "cG93ZXItc3VjY2Vzc2lvbi1hbmQtbGVhZGluZy1kaXNuZXktdGhyb3VnaC11cGhlYXZhbD9wcj0xZjYy"
        "YmVjYjEzNjNiYzg2ZjdjM2JmMWYzNTE5NjQ1N2IyZDAxYmEwODU5NDZhMzc0ODU0YjQ3MjdmOThkZjI5"
        "XHUwMDI2dXRtX2NhbXBhaWduPVdoYXQrSSUyN20rSGVhcmluZystK1NVQlNDUklCRVJTKyUyODklMkYy"
        "NCUyRjI2JTI5XHUwMDI2dXRtX2NvbnRlbnQ9V2hhdCtJJTI3bStIZWFyaW5nKy0rU1VCU0NSSUJFUlMr"
        "JTI4OSUyRjI0JTJGMjYlMjlcdTAwMjZ1dG1fbWVkaXVtPW5ld3NsZXR0ZXJcdTAwMjZ1dG1fc291cmNl"
        "PXB1Y2stY2lvXHUwMDI2dXRtX3Rlcm09ZjZjNjA2MDBjZjgyMDFkMDgyMDEiLCJpbnRlcm5hbCI6ImY2"
        "YzYwNjAwY2Y4MjAxZDA4MjAxIiwibGlua19pZCI6MzA4MDcxN30/86ea63ddbf38ebb013fe02f635b5a79ed")


def test_recognises_newsletter_trackers():
    from dhd_digest.ingest.normalize import is_tracker_url
    assert is_tracker_url(ELINK)
    assert is_tracker_url("https://elinkce0.mail.futureparty.com/ss/c/u001.x/4uc/y/h43/h001.z")
    assert is_tracker_url(GHOST)
    assert is_tracker_url(canonicalize(GHOST))   # still caught after canonicalizing
    assert is_tracker_url(PUCK)
    assert not is_tracker_url("https://spyglass.org/some-essay")
    assert not is_tracker_url("https://www.reddit.com/r/deadbeef")
    assert not is_tracker_url("https://techcrunch.com/2026/09/25/x")


def test_unwraps_puck_without_a_request():
    from dhd_digest.ingest.normalize import unwrap

    class NoNetwork:
        def head(self, url):
            raise AssertionError("should decode locally")
        get = head

    url = unwrap(PUCK, NoNetwork())
    assert url.startswith("https://hbr.org/2026/09/bob-iger-on-power")
    assert canonicalize(url) == ("https://hbr.org/2026/09/"
                                 "bob-iger-on-power-succession-and-leading-disney-through-upheaval")


def test_strips_morning_brew_subscriber_ids():
    u = ("https://www.morningbrew.com/stories/x?mbcid=47650140.3834750&mblid=ed84d5f81c23"
         "&mbuuid=vXLSKRBqVXPKUDdt6i1K53ao&mid=06c70091054f0226d41fc1bc927a656e")
    assert canonicalize(u) == "https://morningbrew.com/stories/x"


def test_rejects_personal_account_links():
    for u in [
        "https://rickrubin.substack.com/action/disable_email?token=eyJ1c2VyX2lk",
        "https://newcomer.co/listen?token=eyJ1c2VyX2lkIjo1NTMzMTA4NzcsImlhdCI6MTc5",
        "https://passport.theankler.com/member/account/delivery",
        "https://cfobrew.com/?email=%7Bemail%7D&mbcid=47650140.3834750",
        "https://arnicas.substack.com/leaderboard?r=95fdel&referrer_token=95fdel",
        "https://importai.substack.com/",
    ]:
        assert canonicalize(u) is None, u
    assert canonicalize("https://importai.substack.com/p/import-ai-400") is not None


def test_url_date_and_staleness():
    from datetime import date
    from dhd_digest.ingest.normalize import is_stale, url_date
    today = date(2026, 9, 28)
    old = "https://morningbrew.com/stories/2022/11/20/disney-replaces-bob-chapek"
    assert url_date(old) == date(2022, 11, 20)
    assert is_stale(url_date(old), today)
    assert url_date("https://hbr.org/2026/09/bob-iger") == date(2026, 9, 28)
    assert not is_stale(url_date("https://techcrunch.com/2026/09/25/x"), today)
    assert url_date("https://newcomer.co/p/kleiner-perkins") is None
    assert not is_stale(None, today)
