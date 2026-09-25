"""Render a draft in the archive's own format, and read one back.

Each item line carries its candidate id in an invisible marker
(`<!-- id:N -->`). `dhd publish` reads the file back through
`parse_published` rather than recomputing a selection, so what gets
marked published is exactly what survived your edits in the PR - delete a
line during review and its marker goes with it.
"""
import re
from pathlib import Path

from ..config import SECTIONS

REVIEW_NOTE = """<!--
REVIEW PASS
  1. Delete anything technically on-target but dull. Expect ~10.
  2. Add parenthetical asides. Historically ~5.4% of links carried one,
     about 8 per issue. They are the only thing a model cannot write for you.
  3. Fill in the Listen / Read / Watch trio at the bottom.
  4. Leave the "<!-- id:... -->" marker on any line you keep - editing the
     blurb or asking for changes is fine, just don't strip the marker.
Merging this PR does not publish. After the issue actually goes out, run:
  dhd publish {issue}
-->
"""

ITEM_LINE = re.compile(
    r"^(?P<blurb>.+?) \[(?P<tag>[^\]]+)\]\((?P<url>[^)]+)\) <!-- id:(?P<id>\d+) -->\s*$"
)


def render(draft: dict) -> str:
    lines = [f"### Issue {draft['issue']} – {draft['date']:%-m.%-d.%y}", "",
              REVIEW_NOTE.format(issue=draft["issue"]), ""]
    for section in SECTIONS:
        items = draft["sections"].get(section) or []
        if not items:
            continue
        lines += [f"**{section}**", ""]
        for it in items:
            lines.append(
                f"{it['blurb']} [{it['tag']}]({it['canonical_url']}) <!-- id:{it['id']} -->")
            lines.append("")
        lines.append("-----")
        lines.append("")
    lines += ["- Listen: ", "- Read: ", "- Watch: ", ""]
    return "\n".join(lines)


def parse_published(path: Path | str) -> list[dict]:
    """Read a (possibly hand-edited) rendered draft back into the items
    that survived review. A line only counts if its id marker is still
    intact, so a deleted line is simply absent here - no diffing needed.
    Returns the id, plus the final blurb text as it appears in the file
    (useful later if published issues ever feed back into the archive).
    """
    text = Path(path).read_text()
    out = []
    for line in text.splitlines():
        m = ITEM_LINE.match(line)
        if m:
            out.append({
                "id": int(m.group("id")),
                "blurb": m.group("blurb"),
                "canonical_url": m.group("url"),
            })
    return out


def write(draft: dict, out_dir: str = "drafts") -> Path:
    path = Path(out_dir) / f"issue-{draft['issue']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(draft))
    counts = {s: len(v) for s, v in draft["sections"].items()}
    total = sum(counts.values())
    print(f"wrote {path} — {total} links {counts}")
    return path
