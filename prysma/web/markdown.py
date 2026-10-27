"""A small, safe Markdown subset for the analysis reports.

The reports are model output built from scraped reviews, so they are untrusted.
Every line is HTML-escaped first; only then is the markup below applied to the
escaped text. The renderer only ever emits the fixed tags it writes itself, so
no tag, attribute or URL from the report can reach the page.

Supported: # / ## / ### headings, - / * / 1. list items (indented items nest
one level), **bold** and Telegram-style *bold*, `code`, and blank lines as
paragraph breaks. Anything else is shown as plain text.
"""
import html
import re

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*•]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d{1,3}[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_STAR_BOLD = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
# Reports mark their metadata line as _italic_. Underscores inside a word
# (snake_case) must not match, hence the boundary checks.
_ITALIC = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_CODE = re.compile(r"`([^`\n]+)`")


def _inline(escaped: str) -> str:
    """Apply inline markup to text that is already escaped."""
    text = _CODE.sub(r"<code>\1</code>", escaped)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _STAR_BOLD.sub(r"<strong>\1</strong>", text)
    return _ITALIC.sub(r"<em>\1</em>", text)


def render_report(text) -> str:
    """Render report text as HTML. Safe for untrusted input."""
    out = []
    paragraph: list[str] = []
    lists: list[str] = []  # open list tags, outermost first; at most two deep

    def close_paragraph():
        if paragraph:
            out.append("<p>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()

    def close_lists(depth=0):
        while len(lists) > depth:
            out.append(f"</li></{lists.pop()}>")

    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = html.escape(raw.rstrip())
        if not line.strip():
            close_paragraph()
            close_lists()
            continue
        if _RULE.match(line):
            close_paragraph()
            close_lists()
            out.append("<hr>")
            continue
        heading = _HEADING.match(line.strip())
        if heading:
            close_paragraph()
            close_lists()
            level = len(heading.group(1)) + 1  # the page already owns h1 and h2 sits on the section
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        item = _BULLET.match(line) or _NUMBERED.match(line)
        if item:
            close_paragraph()
            tag = "ul" if _BULLET.match(line) else "ol"
            depth = 2 if len(item.group(1).expandtabs(4)) >= 2 and lists else 1
            if len(lists) >= depth and lists[depth - 1] != tag:
                close_lists(depth - 1)
            if len(lists) < depth:
                out.append(f"<{tag}><li>")
                lists.append(tag)
            else:
                close_lists(depth)
                out.append("</li><li>")
            out.append(_inline(item.group(2)))
            continue
        if lists:
            # A plain line straight after an item continues that item
            out.append("<br>" + _inline(line.strip()))
            continue
        paragraph.append(_inline(line.strip()))

    close_paragraph()
    close_lists()
    return "\n".join(out)
