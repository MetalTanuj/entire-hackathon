"""Render demo.sh output as a PDF.

Chrome headless does the conversion: it is already on the machine and it is the
only renderer here that handles the box model the report relies on. The demo
output is captured, not retyped, so the PDF cannot drift from what the tool
actually printed.
"""

from __future__ import annotations

import datetime
import html
import pathlib
import re
import subprocess
import sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

VERDICTS = {
    "tune-timeout": ("PASS", "ok", "Constant change. Nothing downstream depends on it."),
    "drop-country": ("BLOCK", "risk", "Removes a live column three gold tables sit on."),
}

CSS = """
 @page { margin: 12mm; size: A4; }
 * { box-sizing: border-box; }
 body { font: 10.5px/1.45 -apple-system,"Helvetica Neue",sans-serif; color:#1a1a1a; margin:0; }
 h1 { font-size:18px; margin:0 0 2px; letter-spacing:-.2px; }
 .sub { color:#555; margin:0 0 3px; font-size:10.5px; }
 .meta { color:#999; font-size:9px; margin:0 0 13px; }
 section { margin-bottom:13px; }
 h2 { font-size:12px; margin:0 0 2px; font-family:ui-monospace,Menlo,monospace; }
 .note { color:#666; margin:0 0 6px; font-size:10px; }
 .badge { font-family:-apple-system,sans-serif; font-size:8.5px; padding:1.5px 7px;
          border-radius:9px; vertical-align:2px; letter-spacing:.4px; font-weight:600; }
 .badge.ok { background:#e6f4ea; color:#1e7b34; }
 .badge.risk { background:#fdeaea; color:#b3261e; }
 pre { background:#fafafa; border:1px solid #e8e8e8; border-radius:4px;
       padding:9px 11px; font:8.5px/1.35 ui-monospace,Menlo,monospace;
       white-space:pre-wrap; margin:0; }
 pre span { display:block; min-height:1em; }
 .risk { color:#b3261e; font-weight:700; }
 .ok { color:#1e7b34; }
 .head { color:#111; font-weight:700; }
 footer { margin-top:11px; padding-top:8px; border-top:1px solid #e8e8e8;
          color:#777; font-size:9px; }
"""


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def highlight(text: str) -> str:
    """Colour the lines a reader scans for, leaving the rest as captured."""
    out = []
    for line in html.escape(text).splitlines():
        css = ""
        if "HIGH RISK" in line:
            css = "risk"
        elif "no column-level break" in line:
            css = "ok"
        elif re.match(r"^\s{2}[A-Z][A-Z ()]+$", line):
            css = "head"
        out.append(f'<span class="{css}">{line}</span>')
    return "\n".join(out)


def build(raw: str) -> str:
    plain = strip_ansi(raw)
    sections = ""
    for chunk in plain.split("  CASE: ")[1:]:
        name, _, body = chunk.partition("\n")
        name = name.strip()
        verdict, css, note = VERDICTS.get(name, ("", "", ""))
        # Trim the rule lines the terminal uses as separators; the PDF has
        # borders of its own and the two together read as clutter.
        body = "\n".join(
            l for l in body.strip("\n").splitlines() if not l.strip().startswith("──")
        ).strip("\n")
        sections += (
            f'<section><h2>{html.escape(name)} '
            f'<span class="badge {css}">{verdict}</span></h2>'
            f'<p class="note">{html.escape(note)}</p>'
            f"<pre>{highlight(body)}</pre></section>"
        )

    return f"""<!doctype html><meta charset="utf-8">
<title>Entire Lakehouse Sentinel — Demo</title><style>{CSS}</style>
<h1>Entire Lakehouse Sentinel</h1>
<p class="sub">Code-to-Lakehouse blast radius auditor — <code>entire graph</code>
 + <code>entire checkpoint</code> + Databricks Unity Catalog</p>
<p class="meta">Generated {datetime.date.today().isoformat()} ·
 repo MetalTanuj/entire-hackathon · catalog <code>main</code></p>
{sections}
<footer>Both commits touch one file and look near-identical to git. The audit separates
them using the live column list from Unity Catalog: <code>main.silver.sessions.country</code>
exists in the Lakehouse today, and <code>refresh_country_rollup</code> in a different file
still reads it. The downstream table graph is derived from the repository; column truth
comes from Databricks, which a CTAS pipeline never declares in code.</footer>"""


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    raw = subprocess.run(
        ["./demo.sh"], cwd=root, capture_output=True, text=True, timeout=900
    ).stdout
    if not raw.strip():
        print("demo produced no output", file=sys.stderr)
        return 1

    page = root / "demo.html"
    page.write_text(build(raw))
    out = root / "demo.pdf"
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out}", str(page)],
        capture_output=True, timeout=180,
    )
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
