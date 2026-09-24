"""URL canonicalization and junk filtering.

Only 102 of 29,819 archive URLs ever repeated, so dedup has to be tight.
Most false duplicates come from tracking params, so strip them aggressively.
"""
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx

STRIP_PARAM_PREFIXES = ("utm_", "ck_", "mc_", "_hs", "pk_", "hsa_", "vero_")
STRIP_PARAMS = {
    "fbclid", "gclid", "igshid", "ref", "referrer", "source", "mkt_tok",
    "guce_referrer", "guce_referrer_sig", "guccounter", "amp", "s",
    "recipient_hashed", "recipient_salt", "msdynttrid", "__twitter_impression",
    "ck_subscriber_id", "email_token", "publication_id", "post_id", "triedRedirect",
}
# Params some sites genuinely need. Never strip these.
KEEP_PARAMS = {"v", "id", "p", "story", "articleId", "gid", "t"}

JUNK_PATTERNS = re.compile(
    r"(unsubscribe|manage[-_]?(your)?[-_]?(preferences|subscription)|"
    r"/privacy|/terms|list-manage\.com|mailchi\.mp/.*/unsub|"
    r"twitter\.com/(intent|share)|facebook\.com/sharer|linkedin\.com/share|"
    r"/feed\.xml|\.rss$|substack\.com/(app|signup|profile)|"
    r"apps\.apple\.com/.*app-store-redirect)", re.I)

# Newsletter link wrappers that hide the real destination. Exact hosts for
# one-off ESPs, plus patterns for ESPs that send from a per-customer or
# per-pool subdomain (Substack's mg1/mg2/mg-d0/... Mailgun pools, Sailthru
# and Mailgun's link.<sender>.com convention, Campaign Monitor's cmailNN.com).
REDIRECT_HOSTS = {
    "link.mail.beehiiv.com", "links.substack.com", "email.beehiivstatus.com",
    "click.convertkit-mail.com", "t.co", "lnkd.in", "trk.klclick.com",
    "clicks.aweber.com", "cl.s7.exct.net", "url.us.m.mimecastprotect.com",
    "tracking.tldrnewsletter.com", "e.customeriomail.com",
}
REDIRECT_HOST_PATTERNS = (
    re.compile(r"^email(\.mg[\w-]*)?\.substack\.com$"),
    re.compile(r"^links?\.[\w-]+\.com$"),
    re.compile(r"^[\w-]+\.cmail\d+\.com$"),
)


def is_redirect_host(host: str) -> bool:
    return host in REDIRECT_HOSTS or any(p.match(host) for p in REDIRECT_HOST_PATTERNS)


def unwrap(url: str, client: httpx.Client | None = None, timeout: float = 6.0) -> str:
    """Follow a tracker redirect to the real destination.

    NOTE: this registers a click with the newsletter's ESP. Set
    resolve_redirects=False in the caller if that bothers you; links from
    those hosts will then stay wrapped and mostly get filtered as junk.
    """
    if isinstance(url, bytes):
        url = url.decode("utf-8", "replace")
    host = urlparse(url).netloc.lower()
    if not is_redirect_host(host):
        return url
    close = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        r = client.head(url)
        if r.status_code >= 400:
            r = client.get(url)
        return str(r.url)
    except Exception:
        return url
    finally:
        if close:
            client.close()


def canonicalize(url: str) -> str | None:
    """Return a stable comparison key, or None if the link is junk."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    if JUNK_PATTERNS.search(url):
        return None
    p = urlparse(url)
    host = p.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None

    kept = []
    for k, v in parse_qsl(p.query, keep_blank_values=False):
        lk = k.lower()
        if lk in KEEP_PARAMS:
            kept.append((k, v))
        elif lk in STRIP_PARAMS or lk.startswith(STRIP_PARAM_PREFIXES):
            continue
        else:
            kept.append((k, v))

    path = p.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", urlencode(sorted(kept)), ""))


def domain_of(canonical_url: str) -> str:
    return urlparse(canonical_url).netloc
