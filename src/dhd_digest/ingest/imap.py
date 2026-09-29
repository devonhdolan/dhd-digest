"""Gmail IMAP fallback, if you'd rather not pay for Feedbin.

Requires 2FA plus a 16-character app password. Google has been narrowing this
path, so prefer Feedbin or migrate to the Gmail API with OAuth when it breaks.
"""
import email
import imaplib
import os
import re
from datetime import date, timedelta
from email.header import decode_header
from email.utils import parseaddr

from selectolax.parser import HTMLParser

from .normalize import canonicalize, domain_of


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(
        p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def fetch_messages(since_uid: int = 0, folder: str | None = None,
                   first_run_days: int = 7) -> list[dict]:
    """Messages in `folder` with UID above since_uid. With no checkpoint yet
    (since_uid 0), only the last `first_run_days` - never a whole mailbox's
    history."""
    host = os.environ["IMAP_HOST"]
    folder = folder or os.environ.get("IMAP_FOLDER") or "Newsletters"
    box = imaplib.IMAP4_SSL(host)
    box.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    box.select(f'"{folder}"', readonly=True)

    if since_uid:
        _, data = box.uid("search", None, f"UID {since_uid + 1}:*")
    else:
        since = (date.today() - timedelta(days=first_run_days)).strftime("%d-%b-%Y")
        _, data = box.uid("search", None, f"SINCE {since}")
    uids = [u for u in data[0].split() if int(u) > since_uid]
    out = []
    for uid in uids:
        _, raw = box.uid("fetch", uid, "(RFC822)")
        if not raw or not raw[0]:
            continue
        msg = email.message_from_bytes(raw[0][1])
        html = text = ""
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/html", "text/plain") and not part.get_filename():
                body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", "replace")
                if ctype == "text/html" and not html:
                    html = body
                elif ctype == "text/plain" and not text:
                    text = body
        sender = _decode(msg.get("From", ""))
        out.append({
            "uid": int(uid),
            "sender": sender,
            "sender_addr": parseaddr(sender)[1].lower(),
            "subject": _decode(msg.get("Subject", "")),
            "html": html,
            "text": text,
        })
    box.logout()
    return out


# --- Picks: links the editor forwards in. Always included in the next draft. ---

FORWARD_SUBJECT = re.compile(r"^\s*(fwd?|fw)\s*:", re.I)
# Where the editor's own note ends and the forwarded message begins
# (Gmail, Apple Mail, Outlook).
FORWARD_MARKERS = re.compile(
    r"-{5,}\s*Forwarded message\s*-{5,}|Begin forwarded message:|-{3,}\s*Original Message\s*-{3,}",
    re.I)
SIGNATURE = re.compile(r"^--\s*$", re.M)   # the standard "-- " signature delimiter
URL = re.compile(r"https?://[^\s<>\"')\]]+")
MAX_LINKS_IN_FORWARD = 3


def owner_addresses() -> set[str]:
    return {a.strip().lower() for a in os.environ.get("OWNER_EMAILS", "").split(",") if a.strip()}


def is_pick(msg: dict) -> bool:
    """Sent by the editor (OWNER_EMAILS), or forwarded by hand ("Fwd:").
    Newsletters auto-forwarded by a Gmail filter keep their original sender
    and subject, so they don't count."""
    return (msg.get("sender_addr") in owner_addresses()
            or bool(FORWARD_SUBJECT.match(msg.get("subject") or "")))


def _message_text(msg: dict) -> str:
    if msg.get("text"):
        return msg["text"]
    tree = HTMLParser(msg.get("html") or "")
    hrefs = [n.attributes.get("href") or "" for n in tree.css("a[href]")]
    return (tree.text(separator="\n") or "") + "\n" + "\n".join(hrefs)


def pick_links(msg: dict) -> list[dict]:
    """The link(s) the editor meant. Anything in their own note above the
    forwarded part wins. Failing that, a forwarded message with only a few
    links counts whole. A forwarded newsletter full of links is ambiguous:
    return nothing and let it flow through normal scoring."""
    parts = FORWARD_MARKERS.split(_message_text(msg), maxsplit=1)
    own, forwarded = parts[0], (parts[1] if len(parts) > 1 else "")
    own = SIGNATURE.split(own, maxsplit=1)[0]
    own_domains = {a.rsplit("@", 1)[-1] for a in owner_addresses()}

    def urls(chunk: str) -> list[str]:
        seen, out = set(), []
        for u in URL.findall(chunk):
            u = u.rstrip(".,;:!?")
            key = canonicalize(u)
            if key and key not in seen and domain_of(key) not in own_domains:
                seen.add(key)
                out.append(u)
        return out

    chosen = urls(own)
    if not chosen:
        in_forward = urls(forwarded)
        chosen = in_forward if len(in_forward) <= MAX_LINKS_IN_FORWARD else []
    if not chosen:
        print(f"  pick from {msg.get('sender_addr')} ({msg.get('subject')!r}): no single link "
              f"to pin - put the link you want above the forwarded message")
    subject = FORWARD_SUBJECT.sub("", msg.get("subject") or "").strip()
    return [{"raw_url": u, "anchor_text": subject[:200], "context": "",
             "source": "editor pick", "source_title": "editor pick", "pinned": True}
            for u in chosen]


def extract_links(msg: dict) -> list[dict]:
    tree = HTMLParser(msg["html"] or "")
    results = []
    for node in tree.css("a[href]"):
        parent = node.parent
        results.append({
            "raw_url": node.attributes.get("href") or "",
            "anchor_text": (node.text() or "").strip()[:200],
            "context": ((parent.text() or "").strip()[:400] if parent else ""),
            "source": msg["sender"],
            "source_title": msg["sender"],
        })
    return results
