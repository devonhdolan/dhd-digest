"""Render a draft in the archive's own format."""
from pathlib import Path

from ..config import SECTIONS

REVIEW_NOTE = """<!--
REVIEW PASS
  1. Delete anything technically on-target but dull. Expect ~10.
  2. Add parenthetical asides. Historically ~5.4% of links carried one,
     about 8 per issue. They are the only thing a model cannot write for you.
  3. Fill in the Listen / Read / Watch trio at the bottom.
Merging this PR marks every surviving link as published.
-->
"""


def render(draft: dict) -> str:
    lines = [f"### Issue {draft['issue']} – {draft['date']:%-m.%-d.%y}", "", REVIEW_NOTE, ""]
    for section in SECTIONS:
        items = draft["sections"].get(section) or []
        if not items:
            continue
        lines += [f"**{section}**", ""]
        for it in items:
            lines.append(f"{it['blurb']} [{it['tag']}]({it['canonical_url']})")
            lines.append("")
        lines.append("-----")
        lines.append("")
    lines += ["- Listen: ", "- Read: ", "- Watch: ", ""]
    return "\n".join(lines)


def write(draft: dict, out_dir: str = "drafts") -> Path:
    path = Path(out_dir) / f"issue-{draft['issue']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(draft))
    counts = {s: len(v) for s, v in draft["sections"].items()}
    total = sum(counts.values())
    print(f"wrote {path} — {total} links {counts}")
    return path
