"""URL canonicalization and junk filtering.

Only 102 of 29,819 archive URLs ever repeated, so dedup has to be tight.
Most false duplicates come from tracking params, so strip them aggressively.
"""
import base64
import json
import re
from datetime import date
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx

from ..config import MAX_ARTICLE_AGE_DAYS

STRIP_PARAM_PREFIXES = ("utm_", "ck_", "mc_", "_hs", "pk_", "hsa_", "vero_")
STRIP_PARAMS = {
    "fbclid", "gclid", "igshid", "ref", "referrer", "source", "mkt_tok",
    "guce_referrer", "guce_referrer_sig", "guccounter", "amp", "s",
    "recipient_hashed", "recipient_salt", "msdynttrid", "__twitter_impression",
    "ck_subscriber_id", "email_token", "publication_id", "post_id", "triedRedirect",
    # Morning Brew per-subscriber ids; Puck's per-subscriber referral hash.
    "mbcid", "mblid", "mbuuid", "mid", "pr",
    # beehiiv's click id and per-subscriber login token (Future Party etc.).
    "_bhlid", "jwt_token",
    # Ghost attribution, Spotify share ids, Variety's feed marker.
    "attribution_id", "attribution_type", "si", "dlsi", "stream",
}
# Params some sites genuinely need. Never strip these.
KEEP_PARAMS = {"v", "id", "p", "story", "articleId", "gid", "t"}

JUNK_PATTERNS = re.compile(
    r"(unsubscribe|manage[-_]?(your)?[-_]?(preferences|subscription)|"
    r"/privacy|/terms|list-manage\.com|mailchi\.mp/.*/unsub|"
    r"twitter\.com/(intent|share)|facebook\.com/sharer|linkedin\.com/share|"
    r"/feed\.xml|\.rss$|substack\.com/(app|signup|profile)|"
    r"apps\.apple\.com/.*app-store-redirect|"
    # Per-subscriber links: account pages, one-click unsubscribes and
    # anything carrying a login/email token. Never publishable, and some
    # act on the subscriber's account when clicked.
    r"disable_email|/member/account|/account(/|\?|$)|/leaderboard\b|"
    r"[?&](token|email|referrer_token)=|"
    r"^https?://[\w-]+\.substack\.com/?$)", re.I)

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
    # SendGrid/beehiiv branded click domains: elink22c.strictlyvc.com,
    # elinkce0.mail.futureparty.com.
    re.compile(r"^elink[\w-]*\.([\w-]+\.)+[a-z]+$"),
)
# Trackers that live on the publisher's own domain, recognisable by path.
# Matched against path plus query.
REDIRECT_PATH_PATTERNS = (
    re.compile(r"^/r/[0-9a-f]{8}\?m="),      # Ghost member link tracking (spyglass.org/r/…?m=)
    re.compile(r"^/e/c/[\w-]+(/[\w-]+)?$"),  # Customer.io (email.puck.news/e/c/…)
    re.compile(r"^/ss/c/"),                  # SendGrid click tracking
)


def is_redirect_host(host: str) -> bool:
    return host in REDIRECT_HOSTS or any(p.match(host) for p in REDIRECT_HOST_PATTERNS)


def is_tracker_url(url: str) -> bool:
    p = urlparse(url)
    path_query = p.path + (f"?{p.query}" if p.query else "")
    return (is_redirect_host(p.netloc.lower())
            or any(r.match(path_query) for r in REDIRECT_PATH_PATTERNS))


def decode_embedded(url: str) -> str | None:
    """Some trackers (Customer.io) carry the destination in the URL itself as
    base64 JSON with an `href`. Decode it locally - no request, no click."""
    for segment in urlparse(url).path.split("/"):
        if len(segment) < 40:
            continue
        try:
            data = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        except Exception:
            continue
        if isinstance(data, dict) and str(data.get("href", "")).startswith(("http://", "https://")):
            return data["href"]
    return None


def unwrap(url: str, client: httpx.Client | None = None, timeout: float = 6.0) -> str:
    """Follow a tracker redirect to the real destination.

    NOTE: this registers a click with the newsletter's ESP. Set
    resolve_redirects=False in the caller if that bothers you; links from
    those hosts will then stay wrapped and get dropped at ingest.
    """
    if isinstance(url, bytes):
        url = url.decode("utf-8", "replace")
    if not is_tracker_url(url):
        return url
    embedded = decode_embedded(url)
    if embedded:
        return embedded
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


URL_DATE = re.compile(r"/(20\d{2})/(0?[1-9]|1[0-2])/(?:(0?[1-9]|[12]\d|3[01])/)?")


def url_date(url: str) -> date | None:
    """The publication date many sites put in the path (/2022/11/20/...).
    Month-only paths resolve to the 28th, erring towards 'recent'."""
    m = URL_DATE.search(urlparse(url).path + "/")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 28)
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def is_stale(published: date | None, today: date | None = None) -> bool:
    """Older than MAX_ARTICLE_AGE_DAYS. An unknown date counts as fresh."""
    if published is None:
        return False
    return ((today or date.today()) - published).days > MAX_ARTICLE_AGE_DAYS


def bad_link(url: str) -> bool:
    """Links today's ingest would refuse: trackers, junk and personal links,
    stale dates. Stored candidates can predate those checks."""
    return (is_tracker_url(url) or canonicalize(url) is None
            or is_stale(url_date(url)))


def domain_of(canonical_url: str) -> str:
    return urlparse(canonical_url).netloc
