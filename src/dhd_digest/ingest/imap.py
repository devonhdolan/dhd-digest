"""Gmail IMAP fallback, if you'd rather not pay for Feedbin.

Requires 2FA plus a 16-character app password. Google has been narrowing this
path, so prefer Feedbin or migrate to the Gmail API with OAuth when it breaks.
"""
import email
import imaplib
import os
from email.header import decode_header

from selectolax.parser import HTMLParser


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(
        p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def fetch_messages(since_uid: int = 0) -> list[dict]:
    host = os.environ["IMAP_HOST"]
    folder = os.environ.get("IMAP_FOLDER", "Newsletters")
    box = imaplib.IMAP4_SSL(host)
    box.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    box.select(f'"{folder}"', readonly=True)

    _, data = box.uid("search", None, f"UID {since_uid + 1}:*")
    uids = [u for u in data[0].split() if int(u) > since_uid]
    out = []
    for uid in uids:
        _, raw = box.uid("fetch", uid, "(RFC822)")
        if not raw or not raw[0]:
            continue
        msg = email.message_from_bytes(raw[0][1])
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", "replace")
                break
        out.append({
            "uid": int(uid),
            "sender": _decode(msg.get("From", "")),
            "subject": _decode(msg.get("Subject", "")),
            "html": body,
        })
    box.logout()
    return out


def extract_links(msg: dict) -> list[dict]:
    tree = HTMLParser(msg["html"] or "")
    results = []
    for node in tree.css("a[href]"):
        parent = node.parent
        results.append({
            "raw_url": node.attributes.get("href", ""),
            "anchor_text": (node.text() or "").strip()[:200],
            "context": ((parent.text() or "").strip()[:400] if parent else ""),
            "source": msg["sender"],
            "source_title": msg["sender"],
        })
    return results
