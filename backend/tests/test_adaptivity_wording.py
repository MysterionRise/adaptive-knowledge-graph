"""
Wording gate for the two-label rule (#210).

docs/adaptivity/README.md says what the project may call adaptive and lists phrases that need
evidence first ("Never say these"). No behaviour passes its tests yet, so the README, the demo
documents and the slides must not use those phrases. This module scans them and fails with
file:line and the phrase.

A sentence that says the thing is NOT done ("There is no item response theory (IRT) model.") is
allowed only when it is listed in APPROVED: the exact sentence, in one document, under one
heading, with the reason. There is no "the line contains 'not'" shortcut. When the gate fails,
reword the document to say what the code does; add to APPROVED only for such a sentence.

What the gate does not cover: it knows the phrases in OVERCLAIMS and nothing else. Outside
"adaptive quizzes", the word "adaptive" is not gated, because the project name, the
/quiz/generate-adaptive endpoint, the interface labels the documents quote ("Adaptive Mode") and
their statements of what education teams need ("adaptive practice") all use it. A reviewer still
has to read a new sentence that presents a behaviour as adaptive in other words.

Not scanned: docs/adaptivity/ (it defines the list), docs/archive/ and docs/evals/.
"""

import bisect
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# The never-say list of docs/adaptivity/README.md ("Two labels and three tests"), plus the two
# phrases in NOT_FROM_THE_LIST. Each pattern is matched, ignoring case, against a document's
# words joined by single spaces, so a phrase also matches when it is wrapped over two lines,
# sits in a block quote or carries inline markup. Markup inside a hyphenated word leaves a space
# next to the hyphen ("<strong>auto</strong>-targets" reads "auto -targets"), which is why the
# separators are "[ -]+" and not one character.
OVERCLAIMS: dict[str, str] = {
    # personalised, personalized, personalisation, personalizes, ...
    "personalised": r"personali[sz]",
    # "adapts to each learner", "adapted to every student", "adapting to the learner's level",
    # "adapts to each individual learner", "adapts to all learners"
    "adapts to each learner": (
        r"\badapt(?:s|ed|ing)? to "
        r"(?:(?:each|every|the|an?|all|individual) ){0,2}(?:learner|student)"
    ),
    # "calibrated difficulty", "calibrated question difficulty", "calibrated-difficulty quizzes";
    # not "uncalibrated"
    "calibrated difficulty": r"\bcalibrated[ -]+(?:\w+[ -]+)?difficulty",
    "mastery accuracy": r"\bmastery accuracy\b|\baccurate mastery\b",
    # "learning gains", "learning gain", "learning-gain"
    "learning gains": r"\blearning[ -]+gains?\b",
    # Any mention: the model does not exist, so only an approved sentence may name it
    "IRT": r"\bIRT\b|\bitem[ -]+response[ -]+theory\b",
    # "auto-targets", "auto targets", "auto-targeting", "automatically targets"
    "auto-targets": r"\bauto(?:matically)?[ -]*target",
    # "adaptive quizzes", "an adaptive quiz", "adaptive-quiz generation"; not "non-adaptive quiz"
    "adaptive quizzes": r"(?<!\bnon-)\badaptive[ -]+quiz(?:zes)?\b",
}
# Rules that are not entries of the note's never-say list:
# - "auto-targets" is the wording of the slide the note found ("Difficulty auto-targets student
#   mastery level");
# - "adaptive quizzes" is what issue #210 found in the README. No behaviour passes the note's
#   tests for "adaptive", and no proper name, endpoint or interface label uses the phrase.
NOT_FROM_THE_LIST = frozenset({"auto-targets", "adaptive quizzes"})
_PATTERNS = {rule: re.compile(pattern, re.IGNORECASE) for rule, pattern in OVERCLAIMS.items()}


@dataclass(frozen=True)
class Approved:
    """One sentence that may contain a never-say phrase because it says the thing is not done."""

    path: str  # the only document it is approved in, relative to the repository root
    section: str  # the heading it must stand under
    # The exact words; line breaks and Markdown emphasis do not matter. It must be a whole
    # sentence or list item in the document: words put in front of it or after it, inside the
    # same sentence, end the approval.
    sentence: str
    reason: str


APPROVED: tuple[Approved, ...] = (
    Approved(
        path="README.md",
        section="Project status and limitations",
        sentence="There is no item response theory (IRT) model.",
        reason="A listed limitation: it says the model does not exist.",
    ),
    Approved(
        path="docs/demo/README.md",
        section="Demo scope",
        sentence=(
            "Boundaries: no LMS or LTI integration, no tenant model, no compliance "
            "certification and no psychometrically calibrated IRT."
        ),
        reason="The demo's boundaries: it lists IRT among the things the demo does not have.",
    ),
    Approved(
        path="docs/demo/CLIENT_PILOT_PROPOSAL.md",
        section="Explicit non-goals",
        sentence="No calibrated IRT claims without learner response data.",
        reason="A non-goal of the pilot: it rules the claim out.",
    ),
    Approved(
        path="docs/demo/PORTFOLIO_CASE_STUDY.md",
        section="No adaptive claim yet",
        sentence="The project makes no claims of calibrated IRT without learner response data.",
        reason="It says the claim is not made.",
    ),
    Approved(
        path="docs/demo/DEMO_PLAYBOOK.md",
        section="Claims to avoid",
        sentence="Full IRT or psychometric validation.",
        reason='An item of the "Claims to avoid" list; the heading carries the negation.',
    ),
    Approved(
        path="docs/demo/DEMO_PLAYBOOK.md",
        section="Claims to avoid",
        sentence="Adaptive quizzes or practice.",
        reason='An item of the "Claims to avoid" list; the heading carries the negation.',
    ),
    Approved(
        path="docs/demo/CLIENT_DEMO_30MIN.md",
        section="Claims to avoid",
        sentence="Adaptive quizzes or practice (see the note under 19\N{EN DASH}24 min)",
        reason='An item of the "Claims to avoid" list; the heading carries the negation.',
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str  # the key in OVERCLAIMS
    text: str  # the words that matched

    def __str__(self) -> str:
        return f'{self.path}:{self.line}: "{self.text}" (never-say phrase: {self.rule})'


# ---------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------

_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
# "content" is the text of a <meta name="description"> tag, which link previews show
_SHOWN_ATTRIBUTE = re.compile(
    r"""\b(?:alt|title|aria-label|content)\s*=\s*(?:"([^"]*)"|'([^']*)')"""
)
_LINK = re.compile(r"""!?\[([^\]]*)\]\([^()\s]*(?:\s+(?:"[^"]*"|'[^']*'))?\)""")
_QUOTE_PREFIX = re.compile(r"^[ \t]*(?:>[ \t]?)+")
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)[ \t#]*$")
_FENCE = re.compile(r"^ {0,3}(?:```|~~~)")
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+")
_EDGE_UNDERSCORES = re.compile(r"(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])")
_SENTENCE_END = re.compile(r"""[.!?]["')\]]*$""")
# Unicode hyphens and the en dash become "-"; soft hyphens and zero-width spaces disappear
_CHARACTERS = str.maketrans(
    {
        "\N{HYPHEN}": "-",
        "\N{NON-BREAKING HYPHEN}": "-",
        "\N{EN DASH}": "-",
        "\N{SOFT HYPHEN}": None,
        "\N{ZERO WIDTH SPACE}": None,
    }
)
# Stands between two blocks (paragraphs, headings, list items). No pattern and no approved
# sentence can reach across it.
_BREAK = "\N{PILCROW SIGN}"


def _without_comments(line: str) -> str:
    """
    The line without the HTML comments that open and close on it.

    A comment that is still open at the end of the line stays and is read as text, so a phrase
    in it is reported. This is plain string search and not a pattern, because the gate reads
    text and must not be mistaken for (or reused as) an HTML sanitiser.
    """
    kept: list[str] = []
    position = 0
    while (start := line.find("<!--", position)) != -1:
        end = line.find("-->", start + 4)
        if end == -1:
            break
        kept.append(line[position:start])
        position = end + 3
    kept.append(line[position:])
    return "".join(kept)


def _tag_text(tag: re.Match[str]) -> str:
    """What a reader sees of an HTML tag: its alt, title, aria-label and content text."""
    shown = _SHOWN_ATTRIBUTE.findall(tag.group(0))
    return " " + " ".join(double or single for double, single in shown) + " "


def _words(line: str) -> list[str]:
    """The words of one source line, without HTML tags, entities and Markdown markup."""
    line = html.unescape(_TAG.sub(_tag_text, _without_comments(line))).translate(_CHARACTERS)
    line = _LINK.sub(r"\1", _QUOTE_PREFIX.sub("", line)).replace(_BREAK, " ")
    line = _EDGE_UNDERSCORES.sub("", re.sub(r"[*`~]", "", line).replace("|", " "))
    return line.split()


def _plain(text: str) -> str:
    return " ".join(word for line in text.splitlines() for word in _words(line))


class _Flat:
    """
    A document as one line of single-spaced words that remembers where each word came from.

    Wrapped lines of one paragraph, list item or block quote join. A blank line, a heading and
    the start of a list item put a _BREAK between the words, so a phrase is not assembled from
    two blocks ("## Calibrated" followed by a paragraph that starts with "Difficulty").
    """

    def __init__(self, text: str) -> None:
        self.words: list[str] = []
        self.lines: list[int] = []
        self.sections: list[str] = []
        section, fenced = "", False
        for number, line in enumerate(text.splitlines(), start=1):
            if _FENCE.match(line):
                fenced = not fenced
            heading = None if fenced else _HEADING.match(line)
            if heading:
                section = " ".join(_words(heading.group(1)))
                line = heading.group(1)
            else:
                line = _QUOTE_PREFIX.sub("", line)
            item = None if heading else _LIST_ITEM.match(line)
            words = _words(line[item.end() :] if item else line)
            if heading or item or not words:
                words.insert(0, _BREAK)
            if heading:
                words.append(_BREAK)
            for word in words:
                self.words.append(word)
                self.lines.append(number)
                self.sections.append(section)
        self.text = " ".join(self.words)
        self.starts: list[int] = []
        offset = 0
        for word in self.words:
            self.starts.append(offset)
            offset += len(word) + 1

    def word_at(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset) - 1

    def _opens_a_sentence(self, index: int) -> bool:
        """The word starts a block, or the word before it ends a sentence."""
        if index == 0:
            return True
        before = self.words[index - 1]
        return before == _BREAK or bool(_SENTENCE_END.search(before))

    def _closes_a_sentence(self, index: int) -> bool:
        """The word ends a sentence, or it is the last word of its block."""
        if _SENTENCE_END.search(self.words[index]) or index + 1 == len(self.words):
            return True
        return self.words[index + 1] == _BREAK

    def occurrences(self, sentence: str, section: str) -> list[tuple[int, int]]:
        """Spans of the exact sentence, as a whole sentence or list item under the given heading."""
        spans: list[tuple[int, int]] = []
        start = self.text.find(sentence) if sentence else -1
        while start != -1:
            end = start + len(sentence)
            first, last = self.word_at(start), self.word_at(end - 1)
            whole_words = self.starts[first] == start and self.text[end : end + 1] in ("", " ")
            whole_sentence = self._opens_a_sentence(first) and self._closes_a_sentence(last)
            if whole_words and whole_sentence and self.sections[first] == section:
                spans.append((start, end))
            start = self.text.find(sentence, start + 1)
        return spans


def find_overclaims(text: str, path: str, approved: Sequence[Approved] = APPROVED) -> list[Finding]:
    """Every never-say phrase in the text that is not inside a sentence approved for this path."""
    flat = _Flat(text)
    allowed = [
        span
        for entry in approved
        if entry.path == path
        for span in flat.occurrences(_plain(entry.sentence), _plain(entry.section))
    ]
    findings = []
    for rule, pattern in _PATTERNS.items():
        for match in pattern.finditer(flat.text):
            if any(start <= match.start() and match.end() <= end for start, end in allowed):
                continue
            first, last = flat.word_at(match.start()), flat.word_at(match.end() - 1)
            words = " ".join(flat.words[first : last + 1])
            findings.append(Finding(path=path, line=flat.lines[first], rule=rule, text=words))
    return sorted(findings, key=lambda finding: (finding.line, finding.rule))


def scanned_documents(root: Path) -> list[Path]:
    """README.md, every Markdown file under docs/demo/ and every slide deck in demo-slides/."""
    return [
        root / "README.md",
        *sorted((root / "docs" / "demo").rglob("*.md")),
        *sorted((root / "demo-slides").glob("*.html")),
    ]


def scan(root: Path, approved: Sequence[Approved] = APPROVED) -> list[Finding]:
    findings = []
    for document in scanned_documents(root):
        path = document.relative_to(root).as_posix()
        findings += find_overclaims(document.read_text(encoding="utf-8"), path, approved)
    return findings


# ---------------------------------------------------------------------------
# The committed documents
# ---------------------------------------------------------------------------


def test_documents_do_not_use_the_never_say_phrases():
    findings = scan(REPO_ROOT)
    assert not findings, (
        "docs/adaptivity/README.md does not allow these phrases until its tests pass.\n"
        + "\n".join(str(finding) for finding in findings)
        + "\nSay what the code does instead. Only if the sentence says the thing is NOT done, "
        "add it to APPROVED in this file with the reason."
    )


def test_the_scan_covers_the_readme_every_demo_document_and_the_slides():
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in scanned_documents(REPO_ROOT)}
    demo_documents = {
        f"docs/demo/{entry.name}"
        for entry in (REPO_ROOT / "docs" / "demo").iterdir()
        if entry.suffix == ".md"
    }
    expected = {"README.md", "demo-slides/index.html", "docs/demo/CLIENT_LEAVE_BEHIND.md"}
    assert expected | demo_documents <= scanned
    # docs/adaptivity/ defines the list and quotes it; the archive and the evaluation reports
    # are records
    assert not [
        path
        for path in scanned
        if path.startswith(("docs/adaptivity/", "docs/archive/", "docs/evals/"))
    ]


def test_the_checker_covers_the_never_say_list_of_the_design_note():
    note = _plain((REPO_ROOT / "docs" / "adaptivity" / "README.md").read_text(encoding="utf-8"))
    never_say = re.search(r"Never say these (.*?) ## ", note)
    assert never_say, 'docs/adaptivity/README.md no longer has its "Never say these" list'
    phrases = re.findall(r'"([^"]+)"', never_say.group(1))
    assert NOT_FROM_THE_LIST < set(OVERCLAIMS)
    # Every other rule is an entry of the list, under the list's own wording
    assert sorted(phrases) == sorted(set(OVERCLAIMS) - NOT_FROM_THE_LIST)
    for phrase in phrases:
        findings = find_overclaims(phrase, "README.md", approved=())
        assert [finding.rule for finding in findings] == [phrase]


def test_every_approved_sentence_is_in_its_document_and_needs_the_approval():
    scanned = {
        path.relative_to(REPO_ROOT).as_posix(): path for path in scanned_documents(REPO_ROOT)
    }
    assert len({(entry.path, entry.sentence) for entry in APPROVED}) == len(APPROVED)
    for entry in APPROVED:
        assert entry.reason.strip(), entry
        assert entry.path in scanned, f"{entry.path} is not a scanned document"
        flat = _Flat(scanned[entry.path].read_text(encoding="utf-8"))
        assert flat.occurrences(_plain(entry.sentence), _plain(entry.section)), (
            f"{entry.path}: the approved sentence is no longer under "
            f'"{entry.section}": {entry.sentence!r}. Remove or update the entry.'
        )
        # Without the approval the sentence is a finding, so the entry is not dead weight
        assert find_overclaims(entry.sentence, entry.path, approved=()), entry


# ---------------------------------------------------------------------------
# The checker itself, on synthetic text
# ---------------------------------------------------------------------------

FLAGGED = [
    # Both spellings, any case, any ending
    ("a personalized learning path", "personalised"),
    ("a personalised learning path", "personalised"),
    ("PERSONALISED quizzes", "personalised"),
    ("Personalization of every quiz", "personalised"),
    ("The tutor personalises its answers.", "personalised"),
    # The two overclaims the design note found
    ("practice adapts to each learner's mastery", "adapts to each learner"),
    ("Difficulty auto-targets student mastery level", "auto-targets"),
    ("The quiz ADAPTS TO EACH LEARNER.", "adapts to each learner"),
    ("Quizzes adapted to every student", "adapts to each learner"),
    ("adapting to the learner's level", "adapts to each learner"),
    ("It will adapt to students over time.", "adapts to each learner"),
    ("practice adapts to each individual learner", "adapts to each learner"),
    ("The tutor adapts to all learners.", "adapts to each learner"),
    ("calibrated difficulty", "calibrated difficulty"),
    ("Calibrated question difficulty", "calibrated difficulty"),
    ("calibrated-difficulty quizzes", "calibrated difficulty"),
    ("reports mastery accuracy per topic", "mastery accuracy"),
    ("an accurate mastery estimate", "mastery accuracy"),
    ("measurable learning gains", "learning gains"),
    ("a learning-gain study", "learning gains"),
    ("An IRT model sets the difficulty.", "IRT"),
    ("irt-based difficulty", "IRT"),
    ("Item Response Theory places each question", "IRT"),
    ("The quiz auto targets your level", "auto-targets"),
    ("Difficulty automatically targets student mastery level", "auto-targets"),
    ("Difficulty auto\N{EN DASH}targets student mastery level", "auto-targets"),
    # What issue #210 found in the README
    (
        "cited answers and adaptive quizzes, running entirely on your own machine",
        "adaptive quizzes",
    ),
    ("Generate an adaptive quiz.", "adaptive quizzes"),
    ("Take an Adaptive Quiz", "adaptive quizzes"),
    ("Adaptive-quiz generation", "adaptive quizzes"),
    # A negation is not an approval
    ("The quizzes are not personalised.", "personalised"),
    ("There is no IRT model.", "IRT"),
    ("We never claim learning gains.", "learning gains"),
    ("These are not adaptive quizzes.", "adaptive quizzes"),
]


@pytest.mark.parametrize(("text", "rule"), FLAGGED)
def test_each_phrase_is_flagged(text, rule):
    findings = find_overclaims(f"# Title\n\n{text}\n", "docs/demo/X.md", approved=())
    assert [(finding.line, finding.rule) for finding in findings] == [(3, rule)]


LAYOUTS = [
    # Wrapped over two lines: reported on the line where the phrase starts
    ("First line.\npractice adapts to each\nlearner's mastery\n", 2),
    ("First line.\n\n> Say that practice adapts to\n> each learner's mastery.\n", 3),
    ("- answers cite sources\n- practice adapts\n  to each learner\n", 2),
    ("| Area | State |\n| --- | --- |\n| Practice | adapts to each learner |\n", 3),
    ("Practice **adapts** to *each* learner.\n", 1),
    ("Practice _adapts to each learner_.\n", 1),
    ("Practice [adapts to each learner](../adaptivity/README.md).\n", 1),
    ('<span class="step-detail">Practice adapts to <strong>each</strong> learner</span>\n', 1),
    ("<p>Practice adapts to each<br/>learner&rsquo;s mastery</p>\n", 1),
    ("<p>Practice adapts&nbsp;to each learner</p>\n", 1),
    ('<img src="quiz.png" alt="Practice adapts to each learner">\n', 1),
    ('<meta name="description" content="A tutor that adapts to each learner" />\n', 1),
    ("<p>Practice adapts to each<!-- hidden --> learner</p>\n", 1),
    ("<p>Practice <!-- one -->adapts to <!-- two -->each learner</p>\n", 1),
    # A comment that does not close on its line is read as text, so the phrase in it is found
    ("Quizzes. <!-- to do: say that practice adapts to each learner\n-->\n", 1),
    ('Practice [adapts](../adaptivity/README.md "what adaptive means") to each learner.\n', 1),
    ("```text\npractice adapts to each learner\n```\n", 2),
]


@pytest.mark.parametrize(("text", "line"), LAYOUTS)
def test_a_phrase_is_found_whatever_the_layout(text, line):
    findings = find_overclaims(text, "docs/demo/X.md", approved=())
    assert [(finding.line, finding.rule) for finding in findings] == [
        (line, "adapts to each learner")
    ]


# Markup or a line break inside a hyphenated phrase
SPLIT_COMPOUNDS = [
    ("<span>Difficulty <strong>auto</strong>-targets student mastery level</span>", "auto-targets"),
    ("Difficulty auto-<em>targets</em> student mastery level", "auto-targets"),
    ("Difficulty auto-\ntargets student mastery level", "auto-targets"),
    ("measurable learning-<em>gains</em>", "learning gains"),
    ("item-<b>response</b> theory places each question", "IRT"),
    ("Take an <strong>adaptive</strong>-quiz", "adaptive quizzes"),
]


@pytest.mark.parametrize(("text", "rule"), SPLIT_COMPOUNDS)
def test_a_hyphenated_phrase_is_found_with_markup_inside(text, rule):
    findings = find_overclaims(text, "demo-slides/index.html", approved=())
    assert [(finding.line, finding.rule) for finding in findings] == [(1, rule)]


CLEAN = [
    "Adaptive Knowledge Graph is the project's name.",
    "POST /api/v1/quiz/generate-adaptive returns a quiz.",
    "Generate a quiz with **Adaptive Mode** on (the default).",
    "This is not adaptive yet.",
    "POST /api/v1/quiz/generate returns a non-adaptive quiz.",
    "Difficulty requested by prompt; neither the delivered difficulty nor the mastery "
    "estimate is validated.",
    "Uncalibrated learner model: the BKT parameters were not fitted.",
    "A pilot would add calibration on learner responses.",
    "It is not yet psychometrically calibrated.",
    "There is no calibrated psychometric question bank.",
    "The Neo4j adapter isolates subjects by label prefix.",
    "Content adapted from OpenStax.",
    "STUDENT_IRT_ENABLED is a removed setting.",
    "Wash the dirt off the shirt.",
    "The learner gains access to the learning path.",
    "Set `margin: 0 auto;` on the target element.",
    "KG expansion is skipped automatically; the target index is unchanged.",
    # A phrase is not assembled from two blocks: heading and paragraph, two paragraphs, two
    # list items
    "## Calibrated\n\nDifficulty is requested by prompt.",
    "The text is adapted to\n\n## Students\n\nRead this first.",
    "The checks were calibrated\n\ndifficulty is requested by prompt.",
    "* content that was adapted to\n* each learner profile in the store",
    "- mastery is not adaptive\n- quiz generation needs the LLM",
    # A comment that opens and closes on one line is not shown to a reader
    "Quizzes are generated. <!-- do not write: practice adapts to each learner -->",
]


@pytest.mark.parametrize("text", CLEAN)
def test_ordinary_wording_is_not_flagged(text):
    assert find_overclaims(f"# Title\n\n{text}\n", "docs/demo/X.md", approved=()) == []


def test_a_finding_names_the_file_the_line_and_the_phrase():
    (finding,) = find_overclaims("One.\nTwo.\nPERSONALISED quizzes\n", "README.md", approved=())
    assert str(finding) == 'README.md:3: "PERSONALISED" (never-say phrase: personalised)'


SENTENCE = "There is no item response theory (IRT) model."
ENTRY = Approved(
    path="docs/demo/X.md", section="Known gaps", sentence=SENTENCE, reason="It says there is none."
)


def test_an_approved_sentence_is_not_flagged():
    text = "# X\n\n## Known gaps\n\n- **Uncalibrated.** There is no item\n  response theory (IRT) model.\n"
    assert find_overclaims(text, "docs/demo/X.md", approved=(ENTRY,)) == []
    assert [finding.rule for finding in find_overclaims(text, "docs/demo/X.md", approved=())] == [
        "IRT",
        "IRT",
    ]


@pytest.mark.parametrize(
    ("text", "path"),
    [
        # Another document
        (f"# X\n\n## Known gaps\n\n{SENTENCE}\n", "README.md"),
        # Another heading
        (f"# X\n\n## Features\n\n{SENTENCE}\n", "docs/demo/X.md"),
        # A heading inside a code block does not count
        (f"# X\n\n```bash\n## Known gaps\n```\n\n{SENTENCE}\n", "docs/demo/X.md"),
        # Not the exact sentence
        (
            "# X\n\n## Known gaps\n\nThere is now an item response theory (IRT) model.\n",
            "docs/demo/X.md",
        ),
        (
            "# X\n\n## Known gaps\n\nThere is no item response theory (IRT) modelling gap.\n",
            "docs/demo/X.md",
        ),
    ],
)
def test_an_approval_covers_one_exact_sentence_in_one_document_and_section(text, path):
    assert find_overclaims(text, path, approved=(ENTRY,))


AVOID = Approved(
    path="docs/demo/X.md",
    section="Claims to avoid",
    sentence="Adaptive quizzes or practice (see the note)",
    reason="A list item with no full stop; the heading carries the negation.",
)
CLAIMS = "# X\n\n## Claims to avoid\n\n"


def test_an_approved_list_item_is_not_flagged():
    text = (
        f"{CLAIMS}- Production-ready\n"
        "- Adaptive quizzes or practice\n  (see the note)\n- Certification-grade\n"
    )
    assert find_overclaims(text, "docs/demo/X.md", approved=(AVOID,)) == []
    assert [finding.rule for finding in find_overclaims(text, "docs/demo/X.md", approved=())] == [
        "adaptive quizzes"
    ]


@pytest.mark.parametrize(
    ("text", "entry"),
    [
        # Words in front of the sentence, inside the same sentence
        (f"# X\n\n## Known gaps\n\nIt is not true that {SENTENCE}\n", ENTRY),
        (f"# X\n\n## Known gaps\n\n- We removed the note that said: {SENTENCE}\n", ENTRY),
        (f"{CLAIMS}- We now provide Adaptive quizzes or practice (see the note)\n", AVOID),
        # Words after it, inside the same sentence
        (f"{CLAIMS}- Adaptive quizzes or practice (see the note) are available.\n", AVOID),
        # The words of two list items do not make the sentence
        (f"{CLAIMS}- Adaptive quizzes or practice\n- (see the note)\n", AVOID),
    ],
)
def test_an_approval_covers_a_whole_sentence_or_list_item_only(text, entry):
    assert find_overclaims(text, entry.path, approved=(entry,))


def test_an_approval_does_not_cover_the_rest_of_the_document():
    text = f"# X\n\n## Known gaps\n\n{SENTENCE} An IRT model is planned.\n\nPersonalised quizzes.\n"
    findings = find_overclaims(text, "docs/demo/X.md", approved=(ENTRY,))
    assert [(finding.line, finding.rule) for finding in findings] == [
        (5, "IRT"),
        (7, "personalised"),
    ]


def test_the_committed_approvals_hold_on_synthetic_documents():
    for entry in APPROVED:
        text = f"# Title\n\n## {entry.section}\n\n{entry.sentence}\n"
        assert find_overclaims(text, entry.path) == [], entry
        assert find_overclaims(text, "docs/demo/ELSEWHERE.md"), entry


def test_scan_reads_the_readme_new_demo_documents_and_the_slides(tmp_path):
    files = {
        "README.md": "# Project\n\nIntro.\n\nIt builds a personalized learning path.\n",
        "docs/demo/NEW.md": "# New\n\nPractice adapts to each learner.\n",
        "docs/demo/drafts/DEEP.md": "# Deep\n\nPERSONALISED quizzes\n",
        "demo-slides/index.html": (
            "<html>\n<body>\n"
            '<span class="step-detail">Difficulty auto-targets student mastery level</span>\n'
            "</body>\n</html>\n"
        ),
        # Not scanned: the note that defines the list, the archive, evaluation reports and
        # anything outside the three places
        "docs/adaptivity/README.md": 'Never say "personalised" or "learning gains".\n',
        "docs/archive/review/NOTES.md": "Personalised, calibrated difficulty.\n",
        "docs/evals/latest.md": "mastery accuracy\n",
        "docs/TESTING.md": "IRT\n",
    }
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    assert [(finding.path, finding.line, finding.rule) for finding in scan(tmp_path)] == [
        ("README.md", 5, "personalised"),
        ("docs/demo/NEW.md", 3, "adapts to each learner"),
        ("docs/demo/drafts/DEEP.md", 3, "personalised"),
        ("demo-slides/index.html", 3, "auto-targets"),
    ]
