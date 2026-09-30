"""
OpenStax markup handling shared by the knowledge-graph builder and the RAG chunker.

The philschatz OpenStax mirrors are kramdown Markdown with embedded HTML:

* processing instructions, raw (``<?cnx.eoc class="summary"?>``) or converted to
  elements (``<cnx-pi data-type="cnx.eoc">class="summary" title="Summary"</cnx-pi>``);
* kramdown attribute lists (``**Beringia**{: data-type="term"}``, ``{: #id}``, ``{#eip-38}``);
* HTML tables and MathML, ``<span data-type="media">`` placeholders, images,
  reference-style links and glossary definition lists.

:func:`clean_text` turns that into plain prose while keeping paragraph and
sentence boundaries. :func:`extract_marked_terms` and :func:`extract_glossary`
read the author-marked key terms and glossary definitions, so they must run on
the text *before* it is cleaned.

This module has no project dependencies, so both ``backend.app.kg`` and
``backend.app.rag`` can import it without an import cycle.
"""

import html
import re

_FRONT_MATTER_RE = re.compile(r"\A\s*---\n[\s\S]*?\n---[ \t]*(?:\n|\Z)")
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_PROCESSING_INSTRUCTION_RE = re.compile(r"<\?[\s\S]*?\?>")
_CNX_PI_ELEMENT_RE = re.compile(r"<cnx-pi\b[^>]*>[\s\S]*?</cnx-pi\s*>", re.IGNORECASE)
_IMAGE_RE = re.compile(r'!\[(?:\\.|[^\]\\])*\]\([^)\s]*(?:\s+"[^"]*")?\s*\)')
# Tail of an image whose title contained ")" and was cut short upstream:
#   ...may represent tobacco."){: #CNX_History_01_00_ThreeWomen}
_IMAGE_REMNANT_RE = re.compile(r'(?m)^[^\n]*"\)(?=\{:)')
_ATTRIBUTE_LIST_RE = re.compile(r"\{:[^}\n]*\}")
_HEADER_ID_RE = re.compile(r"\{#[^}\n]*\}")
_LINK_DEFINITION_RE = re.compile(r"(?m)^[ \t]*\[[^\]\n]+\]:[ \t]*\S+.*$")
_FIGURE_REFERENCE_RE = re.compile(
    r"\(?[ \t]*\[\\?\[link\\?\]\](?:\([^)\n]*\)|\[[^\]\n]*\])[ \t]*\)?", re.IGNORECASE
)
_LINK_RE = re.compile(r"\[((?:\\.|[^\]\\\n])+)\](?:\([^)\n]*\)|\[[^\]\n]*\])")
_TAG_RE = re.compile(r"</?([a-zA-Z][\w:.-]*)(?:\s(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?/?>")
_STRAY_ATTRIBUTE_RE = re.compile(
    r"\b(?:data-[\w.-]+|class|title|id|summary|type|target|href|src|alt|xmlns|colspan|rowspan)"
    r"=\"[^\"\n]*\""
)
_TABLE_RULE_RE = re.compile(r"(?m)^[ \t]*\|?(?:[ \t]*:?-{3,}:?[ \t]*\|?)+[ \t]*$")
_HORIZONTAL_RULE_RE = re.compile(r"(?m)[ \t]*(?:\*[ \t]*){3,}$|^[ \t]*(?:-[ \t]*){3,}$")
_CARET_LINE_RE = re.compile(r"(?m)^[ \t]*\^[ \t]*$")
_DEFINITION_LIST_RE = re.compile(r"(?m)^([^\n]*\S[^\n]*)\n:[ \t]+")
_HEADING_MARKER_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+|[ \t]+#+[ \t]*$")
_STRONG_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EMPHASIS_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_UNDERSCORE_EMPHASIS_RE = re.compile(r"(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])")
_LEFTOVER_STARS_RE = re.compile(r"\*{2,}")
_ESCAPE_RE = re.compile(r"\\+([\\`*_{}\[\]()#+\-.!'\":|>~])")
_SPACES_RE = re.compile(r"[ \t\f\v   ]+")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"(?<=\w) +([.,;!?])(?=\s|$)")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Formatting elements whose removal must not split a word ("E<sub>1</sub>" -> "E1").
_INLINE_TAGS = frozenset(
    {"a", "abbr", "b", "cite", "em", "i", "q", "small", "span", "strong", "sub", "sup", "u"}
    | {"mi", "mn", "mo", "mrow", "mspace", "mstyle", "msub", "msubsup", "msup", "mtext"}
)

# ``**term**{: data-type="term"}`` (kramdown) and ``<span data-type="term">term</span>`` (HTML).
_MARKED_TERM_RE = re.compile(r"\*\*([^*\n]+?)\*\*\{:[^}\n]*data-type=\"term\"[^}\n]*\}")
_HTML_TERM_RE = re.compile(
    r"<(?P<tag>[a-z]+)\b[^>]*\bdata-type=\"term\"[^>]*>(?P<term>[^<]{1,120})</(?P=tag)>",
    re.IGNORECASE,
)
# Kramdown definition-list entry: "Beringia\n: an ancient land bridge ...".
_GLOSSARY_ENTRY_RE = re.compile(
    r"(?m)^(?![ \t]*(?:[-*+][ \t]|[>|#]|\d+\.[ \t]))([^\n:]{2,80})\n:[ \t]+(.+)$"
)
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*(?:\{#[^}\n]*\})?[ \t]*$")

STRUCTURAL_SECTION_TITLES: frozenset[str] = frozenset(
    {
        "answer key",
        "critical thinking question",
        "critical thinking questions",
        "exercises",
        "footnotes",
        "further reading",
        "glossary",
        "key terms",
        "problem",
        "problems",
        "references",
        "review question",
        "review questions",
        "self-check question",
        "self-check questions",
        "suggested reading",
    }
)
"""End-of-section headings whose content is not explanatory prose."""


def _replace_tag(match: re.Match[str]) -> str:
    return "" if match.group(1).lower() in _INLINE_TAGS else " "


def clean_text(text: str) -> str:
    """
    Strip OpenStax/kramdown markup and return plain prose.

    Removes front matter, comments, processing instructions (raw ``<?…?>`` and
    ``<cnx-pi>`` elements), images, attribute lists, link definitions, HTML and
    MathML tags and stray ``data-type="…"``-style attributes; unwraps links,
    emphasis and backslash escapes; joins glossary definition lists onto one line;
    decodes HTML entities; collapses whitespace. Paragraph breaks and sentence
    punctuation are preserved.

    Args:
        text: Raw OpenStax Markdown/HTML, or text that is already plain.

    Returns:
        Cleaned text (plain text passes through unchanged apart from whitespace).
    """
    if not text:
        return ""
    text = _FRONT_MATTER_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _PROCESSING_INSTRUCTION_RE.sub("", text)
    text = _CNX_PI_ELEMENT_RE.sub("", text)
    text = _IMAGE_RE.sub("", text)
    text = _IMAGE_REMNANT_RE.sub("", text)
    text = _ATTRIBUTE_LIST_RE.sub("", text)
    text = _HEADER_ID_RE.sub("", text)
    text = _LINK_DEFINITION_RE.sub("", text)
    text = _FIGURE_REFERENCE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _TAG_RE.sub(_replace_tag, text)
    text = _STRAY_ATTRIBUTE_RE.sub("", text)
    text = _TABLE_RULE_RE.sub("", text)
    text = _HORIZONTAL_RULE_RE.sub("", text)
    text = _CARET_LINE_RE.sub("", text)
    text = _DEFINITION_LIST_RE.sub(r"\1: ", text)  # "Beringia\n: a land bridge" -> "Beringia: …"
    text = _HEADING_MARKER_RE.sub("", text)
    # Protect escaped markers so they are not mistaken for emphasis.
    text = text.replace("\\*", "\x00").replace("\\_", "\x01")
    text = _STRONG_RE.sub(r"\2", text)
    text = _EMPHASIS_RE.sub(r"\1", text)
    text = _UNDERSCORE_EMPHASIS_RE.sub(r"\1", text)
    text = _LEFTOVER_STARS_RE.sub("", text)
    text = text.replace("\x00", "*").replace("\x01", "_")
    text = _ESCAPE_RE.sub(r"\1", text)
    text = html.unescape(text)
    text = _SPACES_RE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def extract_marked_terms(text: str) -> list[str]:
    """Author-marked key terms (``data-type="term"``) in order of appearance, unnormalised."""
    terms = [match.group(1) for match in _MARKED_TERM_RE.finditer(text)]
    terms.extend(match.group("term") for match in _HTML_TERM_RE.finditer(text))
    return [term.strip() for term in terms if term.strip()]


def extract_glossary(text: str) -> dict[str, str]:
    """
    Glossary entries (a term line followed by ``: definition``) as ``{term: definition}``.

    Terms are returned as written; definitions are cleaned. The first definition
    of a term wins.
    """
    glossary: dict[str, str] = {}
    for match in _GLOSSARY_ENTRY_RE.finditer(text):
        term = match.group(1).strip()
        definition = clean_text(match.group(2))
        if term and definition and term not in glossary:
            glossary[term] = definition
    return glossary


def strip_structural_sections(text: str) -> str:
    """
    Drop end-of-section scaffolding (review questions, glossary, references, …).

    A section runs from a Markdown heading listed in
    :data:`STRUCTURAL_SECTION_TITLES` to the next heading of the same or a higher
    level. Text without such headings is returned unchanged.
    """
    kept: list[str] = []
    skip_level = 0
    for line in text.split("\n"):
        heading = _HEADING_RE.match(line.strip())
        if heading:
            level = len(heading.group(1))
            if skip_level and level > skip_level:
                continue
            title = clean_text(heading.group(2)).lower().rstrip(":")
            skip_level = level if title in STRUCTURAL_SECTION_TITLES else 0
            if skip_level:
                continue
        elif skip_level:
            continue
        kept.append(line)
    return "\n".join(kept)
