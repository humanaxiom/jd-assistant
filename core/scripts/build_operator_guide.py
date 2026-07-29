"""Render docs/OPERATOR-GUIDE.md -> a self-contained, SFU-branded HTML page.

Single source of truth is the Markdown; this is the ``make guide`` renderer. Reads the
Markdown on **stdin** and writes the HTML to **stdout** (the same host-redirect shape as
``make register``), so it needs no docs mount and no third-party dependency — a small
Markdown subset parser (headings, bold/italic, code, links, lists, block-quotes, tables
with alignment, rules) plus a branded template with light/dark themes and print styles.

Do not hand-edit ``docs/operator-guide.html`` — run ``make guide`` after editing the
Markdown (``make guide-check`` fails if the committed HTML is stale).
"""

from __future__ import annotations

import html
import re
import sys

# The CSS template below is one long string of hand-minified style rules; line length
# there is not meaningful, so E501 is disabled file-wide.
# ruff: noqa: E501

# ── inline formatting ───────────────────────────────────────────────────────

_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+?)\*\*")
_ITAL = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?!\*)")


def inline(text: str) -> str:
    """Format one span of Markdown text to HTML (escape first, then code, links,
    bold, italic — in that order so a marker inside a code span is left alone)."""
    text = html.escape(text, quote=False)
    text = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITAL.sub(r"<em>\1</em>", text)
    return text


# ── block parsing ───────────────────────────────────────────────────────────

_ALIGN = {(True, True): "center", (False, True): "right", (True, False): "left"}


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _alignments(sep: str) -> list[str]:
    out: list[str] = []
    for c in _cells(sep):
        out.append(_ALIGN.get((c.startswith(":"), c.endswith(":")), "left"))
    return out


def render(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    def para(buf: list[str]) -> None:
        if buf:
            out.append(f"<p>{inline(' '.join(x.strip() for x in buf))}</p>")

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank
        if not stripped:
            i += 1
            continue

        # HTML comment (maintainer note) — never rendered; skip to the closing -->
        if stripped.startswith("<!--"):
            while i < n and "-->" not in lines[i]:
                i += 1
            i += 1  # consume the line carrying -->
            continue

        # horizontal rule
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            out.append("<hr>")
            i += 1
            continue

        # heading
        m = re.match(r"(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # table (a | row followed by a |---| separator)
        if (
            stripped.startswith("|")
            and i + 1 < n
            and re.search(r"\|?\s*:?-{2,}", lines[i + 1])
        ):
            header = _cells(lines[i])
            aligns = _alignments(lines[i + 1])
            i += 2
            body: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                body.append(_cells(lines[i]))
                i += 1

            def al(j: int, aligns: list[str] = aligns) -> str:
                a = aligns[j] if j < len(aligns) else "left"
                return f' style="text-align:{a}"' if a != "left" else ""

            t = ['<div class="table-scroll"><table><thead><tr>']
            t += [f"<th{al(j)}>{inline(c)}</th>" for j, c in enumerate(header)]
            t.append("</tr></thead><tbody>")
            for r in body:
                t.append("<tr>")
                t += [f"<td{al(j)}>{inline(c)}</td>" for j, c in enumerate(r)]
                t.append("</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue

        # block-quote (consecutive '>' lines -> recurse on the de-quoted body)
        if stripped.startswith(">"):
            quoted: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render(chr(10).join(quoted))}</blockquote>")
            continue

        # unordered list (supports one level of nesting)
        if re.match(r"\s*[-*]\s+", line):
            out.append("<ul>")
            depth = 0
            while i < n and re.match(r"\s*[-*]\s+", lines[i]):
                indent = len(lines[i]) - len(lines[i].lstrip())
                item = re.sub(r"^\s*[-*]\s+", "", lines[i])
                if indent >= 2 and depth == 0:
                    out.append("<ul>")
                    depth = 1
                elif indent < 2 and depth == 1:
                    out.append("</ul>")
                    depth = 0
                out.append(f"<li>{inline(item)}</li>")
                i += 1
            if depth == 1:
                out.append("</ul>")
            out.append("</ul>")
            continue

        # paragraph (gather until a blank line or a block starter)
        buf = []
        while (
            i < n
            and lines[i].strip()
            and not re.match(r"(#{1,4}\s|>|\s*[-*]\s|\|)", lines[i].strip())
        ):
            buf.append(lines[i])
            i += 1
        para(buf)

    return "\n".join(out)


# ── branded page template ───────────────────────────────────────────────────

_CSS = r"""
:root{
  --bg:#f7f6f6; --panel:#fff; --panel-2:#fbfafb; --ink:#16141a; --muted:#5f5960;
  --line:#e7e4e6; --line-soft:#f0edef; --accent:#cc0633; --accent-ink:#a80428;
  --shadow:0 1px 2px rgba(22,20,26,.04),0 8px 24px -12px rgba(22,20,26,.12);
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,system-ui,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#12121a; --panel:#191922; --panel-2:#1e1e29; --ink:#ecebf1; --muted:#9f99a6;
  --line:#2a2a37; --line-soft:#21212c; --accent:#ff5c7a; --accent-ink:#ff8098;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px -14px rgba(0,0,0,.55);
}}
:root[data-theme="dark"]{
  --bg:#12121a; --panel:#191922; --panel-2:#1e1e29; --ink:#ecebf1; --muted:#9f99a6;
  --line:#2a2a37; --line-soft:#21212c; --accent:#ff5c7a; --accent-ink:#ff8098;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px -14px rgba(0,0,0,.55);
}
:root[data-theme="light"]{
  --bg:#f7f6f6; --panel:#fff; --panel-2:#fbfafb; --ink:#16141a; --muted:#5f5960;
  --line:#e7e4e6; --line-soft:#f0edef; --accent:#cc0633; --accent-ink:#a80428;
  --shadow:0 1px 2px rgba(22,20,26,.04),0 8px 24px -12px rgba(22,20,26,.12);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.62;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.wrap{max-width:900px;margin:0 auto;padding:clamp(1.1rem,3vw,2.4rem)}
a{color:var(--accent-ink);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:4px}
.brand{display:inline-flex;align-items:center;gap:.75rem;margin-bottom:1.35rem}
.brand-mark{font-weight:800;font-size:2.1rem;letter-spacing:-.045em;line-height:.85;color:var(--accent)}
.brand-rule{width:1.5px;align-self:stretch;background:color-mix(in srgb,var(--accent) 45%,var(--line));border-radius:2px}
.brand-name{font-size:.66rem;font-weight:700;letter-spacing:.17em;text-transform:uppercase;color:var(--muted);line-height:1.4}
h1{font-size:clamp(1.9rem,4.4vw,2.7rem);line-height:1.1;letter-spacing:-.02em;font-weight:800;
  margin:0 0 .7rem;text-wrap:balance;padding-bottom:.65rem;border-bottom:2.5px solid var(--accent)}
h2{font-size:1.32rem;letter-spacing:-.01em;font-weight:750;margin:2.6rem 0 .9rem;text-wrap:balance;
  scroll-margin-top:1rem}
h3{font-size:1.06rem;font-weight:700;margin:1.6rem 0 .5rem;letter-spacing:-.005em}
h4{font-size:.82rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  margin:1.2rem 0 .5rem}
p{margin:.65rem 0;max-width:70ch}
ul{margin:.55rem 0;padding-left:1.2rem}
li{margin:.32rem 0;max-width:68ch}
hr{border:0;border-top:1px solid var(--line);margin:2.2rem 0}
strong{font-weight:700}
code{font-family:var(--mono);font-size:.84em;white-space:nowrap;border-radius:6px;padding:.06em .38em;
  background:color-mix(in srgb,var(--accent) 7%,var(--panel-2));
  border:1px solid color-mix(in srgb,var(--accent) 16%,var(--line));
  color:color-mix(in srgb,var(--ink) 84%,var(--accent))}
blockquote{margin:1rem 0;padding:.1rem 0 .1rem .9rem;color:var(--muted);
  border-left:3px solid color-mix(in srgb,var(--accent) 50%,var(--line))}
blockquote p{margin:.35rem 0}
blockquote strong{color:var(--ink)}
.table-scroll{overflow-x:auto;margin:1rem 0;border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{text-align:left;padding:.6rem .75rem;vertical-align:top;border-bottom:1px solid var(--line-soft)}
thead th{font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;font-weight:700;color:var(--muted);
  background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--panel-2)}
td:first-child{font-weight:600}
footer{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--line);font-size:.82rem;color:var(--muted)}
@media print{
  :root,:root[data-theme="dark"],:root[data-theme="light"]{--bg:#fff;--panel:#fff;--panel-2:#fff;
    --ink:#111;--muted:#444;--line:#ccc;--line-soft:#e4e4e4;--accent:#cc0633;--accent-ink:#a80428;--shadow:none}
  body{font-size:10.5px;line-height:1.42}
  .wrap{max-width:none;padding:0 .2in}
  .table-scroll{box-shadow:none;break-inside:avoid}
  h2,h3,table,blockquote{break-inside:avoid}
  thead th{position:static}
  a{color:#111;text-decoration:none}
}
"""

_HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>JD Bank — Operator &amp; User Guide</title>\n"
    "<style>" + _CSS + "</style>\n</head>\n<body>\n"
    '<div class="wrap">\n'
    '<div class="brand" aria-label="Simon Fraser University">'
    '<span class="brand-mark">SFU</span>'
    '<span class="brand-rule" aria-hidden="true"></span>'
    '<span class="brand-name">Simon Fraser<br>University</span></div>\n'
)

_FOOT = (
    "\n<footer>Simon Fraser University · JD Bank — internal documentation.</footer>\n"
    "</div>\n</body>\n</html>\n"
)


def main() -> None:
    sys.stdout.write(_HEAD + render(sys.stdin.read()) + _FOOT)


if __name__ == "__main__":
    main()
