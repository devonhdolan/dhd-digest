from dhd_digest.editor.assemble import with_picks
from dhd_digest.ingest.imap import is_pick, pick_links


def msg(text, subject="", sender="me@example.com", html=""):
    return {"sender_addr": sender, "subject": subject, "text": text, "html": html}


def urls(m):
    return [p["raw_url"] for p in pick_links(m)]


def test_who_counts_as_a_pick(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "me@example.com, Me@Work.com")
    assert is_pick(msg("x", sender="me@example.com"))
    assert is_pick(msg("x", sender="me@work.com"))
    assert is_pick(msg("x", subject="Fwd: Neon buys TIFF drama", sender="someone@else.com"))
    assert is_pick(msg("x", subject="FW: deal", sender="someone@else.com"))
    # A newsletter auto-forwarded by a Gmail filter keeps its sender and subject.
    assert not is_pick(msg("x", subject="StrictlyVC: Tuesday", sender="hello@strictlyvc.com"))


def test_share_sheet_email_pins_its_link(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "me@example.com")
    m = msg("https://deadline.com/2026/09/neon-buys-drama-1236/\n\nSent from my iPhone",
            subject="Neon Buys Drama")
    assert urls(m) == ["https://deadline.com/2026/09/neon-buys-drama-1236/"]
    assert pick_links(m)[0]["pinned"] is True
    assert pick_links(m)[0]["anchor_text"] == "Neon Buys Drama"


def test_note_above_a_forward_wins(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "me@example.com")
    m = msg("include this one https://variety.com/2026/film/news/a24-x/\n\n"
            "---------- Forwarded message ---------\nFrom: Puck\n"
            "https://puck.news/a https://puck.news/b https://puck.news/c https://puck.news/d",
            subject="Fwd: What I'm Hearing")
    assert urls(m) == ["https://variety.com/2026/film/news/a24-x/"]


def test_bare_forward_of_an_article_email_counts_whole(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "")
    m = msg("\n---------- Forwarded message ---------\nFrom: Deadline\n"
            "Read more: https://deadline.com/2026/09/x-1/\n"
            "Unsubscribe: https://deadline.com/unsubscribe?u=1",
            subject="Fwd: Breaking", sender="me@example.com")
    assert urls(m) == ["https://deadline.com/2026/09/x-1/"]   # unsubscribe is junk


def test_bare_forward_of_a_whole_newsletter_is_ambiguous(monkeypatch, capsys):
    monkeypatch.setenv("OWNER_EMAILS", "")
    body = "\n".join(f"https://example.com/story-{i}" for i in range(12))
    m = msg("---------- Forwarded message ---------\n" + body, subject="Fwd: Newsletter")
    assert urls(m) == []
    assert "put the link you want above" in capsys.readouterr().out


def test_signature_and_own_domain_links_are_ignored(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "dhd@example-ventures.com")
    m = msg("https://thewrap.com/x-deal/\n\n--\nDHD | https://example-ventures.com\n"
            "https://www.linkedin.com/in/dhd",
            subject="look", sender="dhd@example-ventures.com")
    assert urls(m) == ["https://thewrap.com/x-deal/"]


def test_html_only_messages_are_read_too(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "me@example.com")
    m = msg("", html='<div>this <a href="https://variety.com/2026/film/news/y/">one</a></div>')
    assert urls(m) == ["https://variety.com/2026/film/news/y/"]


def test_every_pick_survives_the_editor():
    items = [{"id": 1, "pinned": True}, {"id": 2}, {"id": 3, "pinned": True}]
    chosen = [{"id": 2}, {"id": 3, "pinned": True}]          # editor dropped pick 1
    assert [c["id"] for c in with_picks(chosen, items)] == [2, 3, 1]
