"""Render docs/report.md as one self-contained HTML page (docs/report.html).

    uv run python scripts/build_report_html.py              # docs/report.html
    uv run python scripts/build_report_html.py --fragment out.html   # body only, for embedding

The page is static: no scripts, fonts from Google Fonts with system fallbacks, styles inline.
Tables and code blocks scroll inside their own box, so the page never scrolls sideways.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "report.md"
TARGET = ROOT / "docs" / "report.html"
TITLE = "Case-Law Extraction Pipeline"

CSS = """
/* Layout: one reading column of about 70 characters, a sticky table of contents to the left on wide
   screens, tables allowed to run wider than the column inside their own scroll box. */
:root {
  --bg: #f7f8f9;
  --paper: #ffffff;
  --fg: #1c2128;
  --muted: #5b6672;
  --rule: #d6dbe0;
  --accent: #9b1c2e;
  --accent-soft: #f6e9eb;
  --code-bg: #eef1f4;
  --th-bg: #eef1f4;
  --summary-bg: #ffffff;
  --font-body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15181c; --paper: #1c2026; --fg: #e4e8ec; --muted: #9aa5b1; --rule: #343b44;
    --accent: #e0697a; --accent-soft: #3a2228; --code-bg: #242a31; --th-bg: #242a31;
    --summary-bg: #1c2026; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #15181c; --paper: #1c2026; --fg: #e4e8ec; --muted: #9aa5b1; --rule: #343b44;
  --accent: #e0697a; --accent-soft: #3a2228; --code-bg: #242a31; --th-bg: #242a31;
  --summary-bg: #1c2026; color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg); font-family: var(--font-body);
  font-size: 16px; line-height: 1.55;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
  padding-block: 0 48px;
}
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.page { max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: 1fr; gap: 0 48px; }
@media (min-width: 1000px) { .page { grid-template-columns: 240px minmax(0, 1fr); } }
header.masthead {
  grid-column: 1 / -1; padding-block: 40px 24px; border-bottom: 1px solid var(--rule); margin-bottom: 24px;
}
.eyebrow { font-family: var(--font-mono); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 8px; }
header h1 { font-size: clamp(28px, 4vw, 40px); line-height: 1.1; margin: 0 0 12px; letter-spacing: -.01em; text-wrap: balance; font-weight: 600; }
.status { color: var(--muted); max-width: 72ch; margin: 0; font-size: 15px; }
nav.toc { display: none; }
@media (min-width: 1000px) {
  nav.toc { display: block; position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow-y: auto; font-size: 13.5px; padding-right: 8px; }
}
nav.toc .eyebrow { margin-bottom: 10px; }
nav.toc ol { list-style: none; margin: 0; padding: 0; }
nav.toc li { margin: 0; }
nav.toc a { display: block; color: var(--fg); text-decoration: none; padding: 3px 0 3px 10px; border-left: 2px solid var(--rule); }
nav.toc a:hover { color: var(--accent); border-left-color: var(--accent); }
nav.toc ol ol a { padding-left: 22px; color: var(--muted); font-size: 12.5px; }
main { min-width: 0; max-width: 78ch; }
main > section { padding-block: 8px 24px; }
main > section + section { border-top: 1px solid var(--rule); padding-top: 28px; }
h2 { font-size: 26px; line-height: 1.2; margin: 0 0 16px; letter-spacing: -.01em; font-weight: 600; text-wrap: balance; }
h3 { font-size: 18.5px; line-height: 1.3; margin: 32px 0 10px; font-weight: 600; text-wrap: balance; }
h4 { font-size: 16px; margin: 24px 0 8px; font-weight: 600; }
p, ul, ol { margin: 0 0 14px; }
li { margin-bottom: 6px; }
li > p { margin-bottom: 6px; }
strong { font-weight: 600; }
em { color: var(--muted); }
code { font-family: var(--font-mono); font-size: .88em; background: var(--code-bg); padding: 1px 5px; border-radius: 3px; }
pre { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.45; background: var(--code-bg); padding: 14px 16px; border-radius: 4px; overflow-x: auto; margin: 0 0 16px; }
pre code { background: none; padding: 0; font-size: inherit; }
.tw { overflow-x: auto; margin: 0 0 18px; border: 1px solid var(--rule); border-radius: 4px; background: var(--paper); }
table { border-collapse: collapse; font-size: 13.5px; min-width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--rule); vertical-align: top; text-align: left; }
tr:last-child td { border-bottom: 0; }
th { background: var(--th-bg); font-weight: 600; white-space: nowrap; }
td code { white-space: nowrap; }
section.summary { background: var(--summary-bg); border: 1px solid var(--rule); border-top: 3px solid var(--accent); border-radius: 4px; padding: 24px 28px 8px !important; margin-bottom: 24px; }
section.summary + section { border-top: 0; }
section.summary h2 { color: var(--accent); }
section.summary h3 { margin-top: 24px; font-size: 16px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 600; }
section.summary .tw { border-color: var(--rule); }
section.summary td:first-child { font-weight: 600; width: 32%; }
footer { grid-column: 1 / -1; border-top: 1px solid var(--rule); margin-top: 24px; padding-top: 16px; color: var(--muted); font-size: 13px; font-family: var(--font-mono); }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
@media (max-width: 600px) { section.summary { padding: 18px 16px 4px !important; } h2 { font-size: 23px; } }
"""

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600'
    '&family=IBM+Plex+Mono:wght@400;500&display=swap">'
)


def render_body(md_text: str) -> tuple[str, list]:
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "smarty"],
        extension_configs={"toc": {"toc_depth": "2-3"}, "smarty": {"smart_dashes": False}},
    )
    html = md.convert(md_text)
    return html, md.toc_tokens


def split_sections(html: str) -> str:
    """Wrap each h2 and what follows it in <section>; the management summary gets a class."""
    parts = re.split(r"(?=<h2 )", html)
    out = [parts[0]] if parts and not parts[0].startswith("<h2 ") else []
    for part in parts[1 if out else 0 :]:
        m = re.match(r'<h2 id="([^"]+)"', part)
        sec_id = m.group(1) if m else ""
        cls = ' class="summary"' if sec_id == "management-summary" else ""
        out.append(f"<section{cls}>{part}</section>")
    return "\n".join(out)


def toc_html(tokens: list) -> str:
    def items(toks: list) -> str:
        lis = []
        for t in toks:
            sub = f"<ol>{items(t['children'])}</ol>" if t.get("children") else ""
            lis.append(f'<li><a href="#{t["id"]}">{t["name"]}</a>{sub}</li>')
        return "".join(lis)

    return f'<nav class="toc" aria-label="Contents"><p class="eyebrow">Contents</p><ol>{items(tokens)}</ol></nav>'


def build(md_text: str, fragment: bool) -> str:
    lines = md_text.split("\n")
    h1 = lines[0].lstrip("# ").strip()
    status = ""
    for line in lines[1:8]:
        if line.startswith("Status:"):
            status = line[len("Status:") :].strip()
            break
    body_md = "\n".join(line for line in lines[1:] if not line.startswith("Status:"))
    body, toc = render_body(body_md)
    body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    body = split_sections(body)
    built = date.today().isoformat()
    inner = f"""
<div class="page">
<header class="masthead">
  <p class="eyebrow">Project 1 of 4 · report</p>
  <h1>{h1}</h1>
  <p class="status">{markdown.markdown(status)[3:-4]}</p>
</header>
{toc_html(toc)}
<main>
{body}
</main>
<footer>Rendered from docs/report.md on {built}. Repository: caselaw-extraction.</footer>
</div>
"""
    head = f"<title>{TITLE}</title>\n{FONTS}\n<style>{CSS}</style>"
    if fragment:
        return head + inner
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}\n</head>\n<body>{inner}</body>\n</html>\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fragment", type=Path, help="write a body-only fragment to this path")
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--target", type=Path, default=TARGET)
    args = ap.parse_args()
    md_text = args.source.read_text()
    if args.fragment:
        args.fragment.write_text(build(md_text, fragment=True))
        print(args.fragment)
    else:
        args.target.write_text(build(md_text, fragment=False))
        print(args.target)


if __name__ == "__main__":
    main()
