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
