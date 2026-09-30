"""
OpenStax markup handling shared by the knowledge-graph builder and the RAG chunker.

The philschatz OpenStax mirrors are kramdown Markdown with embedded HTML:

* processing instructions, raw (``<?cnx.eoc class="summary"?>``) or converted to
  elements (``<cnx-pi data-type="cnx.eoc">class="summary" title="Summary"</cnx-pi>``);
* kramdown attribute lists (``**Beringia**{: data-type="term"}``, ``{: #id}``, ``{#eip-38}``);
* HTML tables and MathML, ``<span data-type="media">`` placeholders, images,
  reference-style links and glossary definition lists.

:func:`clean_text` turns that into plain prose while keeping paragraph and
sentence boundaries. Formulas stay legible: MathML is written out linearly
("(3,000 – 2,800)/((3,000 + 2,800)/2)", "πr^2") and HTML superscripts become
``^`` ("The HHI is 100^2 = 10,000"). :func:`extract_marked_terms` and
:func:`extract_glossary` read the author-marked key terms and glossary
definitions, so they must run on the text *before* it is cleaned.

The rules only match the markup forms found in the corpora, so prose that merely
looks like markup survives: "if P<MC", "<name>", "Texas A&M", "x**2", "[1][2]".

This module has no project dependencies, so both ``backend.app.kg`` and
``backend.app.rag`` can import it without an import cycle.
"""

import html
import re
from xml.etree import ElementTree

_FRONT_MATTER_RE = re.compile(r"\A\s*---\n[\s\S]*?\n---[ \t]*(?:\n|\Z)")
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_PROCESSING_INSTRUCTION_RE = re.compile(r"<\?[A-Za-z][\w.:-]*(?:\s[\s\S]*?)?\?>")
_CNX_PI_ELEMENT_RE = re.compile(r"<cnx-pi\b[^>]*>[\s\S]*?</cnx-pi\s*>", re.IGNORECASE)
_MATH_RE = re.compile(r"<math\b[^>]*>[\s\S]*?</math\s*>", re.IGNORECASE)
_SUPERSCRIPT_RE = re.compile(r"<sup\b[^>]*>([\s\S]*?)</sup\s*>", re.IGNORECASE)
_IMAGE_RE = re.compile(r'!\[(?:\\.|[^\]\\])*\]\([^)\s]*(?:\s+"[^"]*")?\s*\)')
# Tail of an image whose title contained ")" and was cut short upstream:
#   ...may represent tobacco."){: #CNX_History_01_00_ThreeWomen}
_IMAGE_REMNANT_RE = re.compile(r'(?m)^[^\n]*"\)(?=\{:)')
# "Chapter 1: The Americas* * *" followed by a {: data-type="newline"} attribute list.
_NEWLINE_MARKER_RE = re.compile(r'(?m)[ \t]*(?:\*[ \t]*){3}$(?=\n\{:[^}\n]*data-type="newline")')
_ATTRIBUTE_LIST_RE = re.compile(r"\{:[^}\n]*\}")
_HEADER_ID_RE = re.compile(r"\{#[^}\n]*\}")
_LINK_DEFINITION_RE = re.compile(
    r"(?m)^[ \t]*\[([^\]\n]+)\]:[ \t]*<?(?:https?://|www\.|/|#|\.{1,2}/)[^\s>]*>?"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?[ \t]*$"
)
_FIGURE_REFERENCE_RE = re.compile(
    r"\(?[ \t]*\[\\?\[link\\?\]\](?:\([^)\n]*\)|\[[^\]\n]*\])[ \t]*\)?", re.IGNORECASE
)
_REFERENCE_LINK_RE = re.compile(r"\[((?:\\.|[^\]\\\n])+)\]\[([^\]\n]*)\]")
_INLINE_LINK_RE = re.compile(r"\[((?:\\.|[^\]\\\n])+)\]\(<?[^)\s>]*>?(?:\s+\"[^\"\n]*\")?\)")
# A start or end tag with well-formed attributes; only known element names are removed.
_TAG_RE = re.compile(
    r"</?(?P<name>[a-zA-Z][\w:.-]*)"
    r"(?:\s+[A-Za-z_:][\w:.-]*(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'<>=`]+))?)*"
    r"\s*/?>"
)
_DATA_ATTRIBUTE_RE = re.compile(r"\bdata-[\w.-]+=\"[^\"\n]*\"")
_TABLE_RULE_RE = re.compile(r"(?m)^(?=[^\n]*\|)(?=[^\n]*-{3})[ \t|:\-]+(?:\n|\Z)")
_THEMATIC_BREAK_RE = re.compile(r"(?m)^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_CARET_LINE_RE = re.compile(r"(?m)^[ \t]*\^[ \t]*$")
_DEFINITION_LIST_RE = re.compile(r"(?m)^([^\n]*\S[^\n]*)\n:[ \t]+")
_HEADING_LINE_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_STRONG_RE = re.compile(r"(?<![\w*])\*\*(?=\S)(.+?)(?<=\S)\*\*(?![\w*])")
_EMPHASIS_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_ESCAPE_RE = re.compile(r"\\+([\\`*_{}\[\]()#+\-.!'\":|>~])")
_ENTITY_RE = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_SPACES_RE = re.compile(r"[ \t\f\v   ]+")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"(?<=\w) +([.,;!?])(?=\s|$)")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

_KNOWN_TAGS = frozenset(
    # HTML
    {"a", "abbr", "article", "aside", "audio", "b", "big", "blockquote", "br", "caption"}
    | {"center", "cite", "code", "col", "colgroup", "dd", "del", "details", "dfn", "div"}
    | {"dl", "dt", "em", "embed", "figcaption", "figure", "font", "footer", "h1", "h2"}
    | {"h3", "h4", "h5", "h6", "header", "hr", "i", "iframe", "img", "ins", "kbd", "li"}
    | {"main", "mark", "nav", "nobr", "object", "ol", "p", "param", "picture", "pre", "q"}
    | {"s", "samp", "section", "small", "source", "span", "strike", "strong", "sub"}
    | {"summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr"}
    | {"tt", "u", "ul", "var", "video", "wbr"}
    # MathML (only reached when a <math> block cannot be parsed)
    | {"annotation", "annotation-xml", "maction", "maligngroup", "malignmark", "math"}
    | {"menclose", "merror", "mfenced", "mfrac", "mi", "mlabeledtr", "mmultiscripts", "mn"}
    | {"mo", "mover", "mpadded", "mphantom", "mprescripts", "mroot", "mrow", "ms"}
    | {"mspace", "msqrt", "mstyle", "msub", "msubsup", "msup", "mtable", "mtd", "mtext"}
    | {"mtr", "munder", "munderover", "none", "semantics"}
    # OpenStax
    | {"cnx-pi"}
)

# Formatting elements whose removal must not split a word ("E<sub>1</sub>" -> "E1").
_INLINE_TAGS = frozenset(
    {"a", "abbr", "b", "big", "cite", "code", "del", "dfn", "em", "font", "i", "ins", "kbd"}
    | {"mark", "nobr", "q", "s", "samp", "small", "span", "strike", "strong", "sub", "sup"}
    | {"time", "tt", "u", "var", "wbr"}
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

# ---------------------------------------------------------------------------- formulas

_XML_ENTITIES = frozenset({"amp", "apos", "gt", "lt", "quot"})
_NAMED_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]{1,31});")
_MATH_LEAVES = frozenset({"mi", "mn", "mo", "ms", "mtext"})
_SPACED_OPERATORS = frozenset(
    {"=", "+", "-", "−", "–", "—", "×", "÷", "±", "∓", "<", ">", "≤", "≥", "≠", "≈", "·", "→"}
)
_SIMPLE_OPERAND_RE = re.compile(r"[\w.,%$€£¢'′°]+")
# Superscripts that are not exponents: ordinal suffixes ("21st") and marks ("AP®", "Revenue*").
_NON_EXPONENT_RE = re.compile(r"st|nd|rd|th|[®™©*†‡§¶°]+", re.IGNORECASE)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _is_wrapped(text: str) -> bool:
    """True when the whole of ``text`` is one parenthesised group, "(a + b)"."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    for index, char in enumerate(text):
        depth += (char == "(") - (char == ")")
        if depth == 0 and index < len(text) - 1:
            return False
    return depth == 0


def _operand(node: ElementTree.Element, *, left: bool) -> str:
    """
    Render a fraction/script operand, parenthesising structured multi-term parts.

    A text leaf keeps its outer spacing ("P" "× Q" stays "P × Q"): a left operand
    its leading space, a right operand its trailing space.
    """
    rendered = _render_math(node)
    text = rendered.strip()
    if _local_name(node.tag) in _MATH_LEAVES:
        return rendered.rstrip() if left else rendered.lstrip()
    if _SIMPLE_OPERAND_RE.fullmatch(text) or _is_wrapped(text):
        return text
    return f"({text})"


def _render_math(node: ElementTree.Element) -> str:
    """Linear text for a MathML element: a/b, a^b, a_b, one table row per line."""
    name = _local_name(node.tag)
    if name in ("annotation", "annotation-xml", "mphantom"):
        return ""
    if name == "mo":
        operator = "".join(node.itertext()).strip()
        return f" {operator} " if operator in _SPACED_OPERATORS else operator
    if name in _MATH_LEAVES:
        return "".join(node.itertext())
    if name == "mspace":
        return " "

    children = list(node)
    if name == "semantics":
        return _render_math(children[0]) if children else ""
    if name == "mfrac" and len(children) == 2:
        return f"{_operand(children[0], left=True)}/{_operand(children[1], left=False)}"
    if name == "msup" and len(children) == 2:
        return f"{_operand(children[0], left=True)}^{_operand(children[1], left=False)}"
    if name == "msub" and len(children) == 2:
        return f"{_operand(children[0], left=True)}_{_operand(children[1], left=False)}"
    if name == "msubsup" and len(children) == 3:
        base = _operand(children[0], left=True)
        low, high = (_operand(child, left=False) for child in children[1:])
        return f"{base}_{low.strip()}^{high}"
    if name == "msqrt":
        return f"√({''.join(_render_math(child) for child in children).strip()})"
    if name == "mroot" and len(children) == 2:
        radicand, index = _operand(children[0], left=True), _operand(children[1], left=False)
        return f"{radicand}^(1/{index.strip()})"
    if name == "mfenced":
        separator = (node.get("separators") or ",").strip()[:1] or ","
        inner = f"{separator} ".join(_render_math(child).strip() for child in children)
        return f"{node.get('open', '(')}{inner}{node.get('close', ')')}"
    if name == "mtable":
        return "\n".join(_render_math(child).strip() for child in children)
    if name in ("mtr", "mlabeledtr"):
        cells = (_render_math(child).strip() for child in children)
        return " ".join(cell for cell in cells if cell)
    if name in ("munder", "mover", "munderover"):
        return " ".join(_render_math(child).strip() for child in children)
    return "".join(_render_math(child) for child in children)


def _linearize_math(block: str) -> str | None:
    """Linear text for a ``<math>`` block, or None when it is not well-formed XML."""
    xml = _NAMED_ENTITY_RE.sub(
        lambda m: m.group(0) if m.group(1) in _XML_ENTITIES else html.unescape(m.group(0)),
        block,
    )
    try:
        # A fragment that starts at <math> cannot carry a DTD, so no entity expansion.
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    lines = (" ".join(line.split()) for line in _render_math(root).split("\n"))
    text = "\n".join(line for line in lines if line)
    # Keep "<" and "&" out of the later tag pass; entities are decoded at the end.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _replace_math(match: re.Match[str]) -> str:
    linear = _linearize_math(match.group(0))
    return match.group(0) if linear is None else f" {linear} "


def _decode_entities(text: str) -> str:
    """Decode well-formed entities only; "Texas A&M" and "&copy symbol" stay as written."""
    return _ENTITY_RE.sub(lambda m: html.unescape(m.group(0)), text)


def _replace_superscript(match: re.Match[str]) -> str:
    """``<sup>`` as an exponent ("100^2"), except ordinals, marks and footnote links."""
    inner = match.group(1)
    if "footnote" in inner.lower():
        return ""
    content = _decode_entities(_TAG_RE.sub("", _ATTRIBUTE_LIST_RE.sub("", inner))).strip()
    if not content:
        return ""
    if _NON_EXPONENT_RE.fullmatch(content):
        return inner
    exponent = content if _SIMPLE_OPERAND_RE.fullmatch(content) else f"({content})"
    return "^" + exponent.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------------------ cleaning


def _replace_tag(match: re.Match[str]) -> str:
    name = match.group("name").lower()
    if name not in _KNOWN_TAGS:  # "if P<MC ... Q>0", "<name>": prose, not markup
        return match.group(0)
    return "" if name in _INLINE_TAGS else " "


def _unwrap_reference_links(text: str) -> str:
    """``[text][1]`` -> "text" when ``[1]: url`` is defined; "[1][2][3]" citations stay."""
    labels = {label.lower() for label in _LINK_DEFINITION_RE.findall(text)}
    if not labels:
        return text

    def replace(match: re.Match[str]) -> str:
        label = (match.group(2) or match.group(1)).lower()
        return match.group(1) if label in labels else match.group(0)

    return _REFERENCE_LINK_RE.sub(replace, text)


def clean_text(text: str) -> str:
    """
    Strip OpenStax/kramdown markup and return plain prose.

    Removes front matter, comments, processing instructions (raw ``<?…?>`` and
    ``<cnx-pi>`` elements), images, attribute lists, link definitions, HTML tags
    and ``data-type="…"`` attributes; writes MathML and superscripts out linearly;
    unwraps links, emphasis and backslash escapes; joins glossary definition lists
    onto one line; decodes HTML entities; collapses whitespace. Paragraph breaks and
    sentence punctuation are preserved.

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
    text = _MATH_RE.sub(_replace_math, text)
    text = _SUPERSCRIPT_RE.sub(_replace_superscript, text)
    text = _IMAGE_RE.sub("", text)
    text = _IMAGE_REMNANT_RE.sub("", text)
    text = _NEWLINE_MARKER_RE.sub("", text)
    text = _ATTRIBUTE_LIST_RE.sub("", text)
    text = _HEADER_ID_RE.sub("", text)
    text = _unwrap_reference_links(text)
    text = _LINK_DEFINITION_RE.sub("", text)
    text = _FIGURE_REFERENCE_RE.sub("", text)
    text = _INLINE_LINK_RE.sub(r"\1", text)
    text = _TAG_RE.sub(_replace_tag, text)
    text = _DATA_ATTRIBUTE_RE.sub("", text)
    text = _TABLE_RULE_RE.sub("", text)
    text = _THEMATIC_BREAK_RE.sub("", text)
    text = _CARET_LINE_RE.sub("", text)
    text = _DEFINITION_LIST_RE.sub(r"\1: ", text)  # "Beringia\n: a land bridge" -> "Beringia: …"
    text = _HEADING_LINE_RE.sub(r"\1", text)
    # Protect escaped markers so they are not mistaken for emphasis.
    text = text.replace("\\*", "\x00")
    text = _STRONG_RE.sub(r"\1", text)
    text = _EMPHASIS_RE.sub(r"\1", text)
    text = text.replace("\x00", "*")
    text = _ESCAPE_RE.sub(r"\1", text)
    text = _decode_entities(text)
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
