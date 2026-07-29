# recipe_parser/validation/coverage.py
"""
Audits how much of the *source document* survived into the parsed model.

Every other pass inspects what the parser produced. This one inspects what it threw
away, which is the failure mode nothing else can see: a fenced code block, an HTML
block, or a blockquote nested inside a numbered step simply never appears in the
output, and no diagnostic is raised because no rule ever ran on it.

What it catches is missing *blocks*, not mangled *fields*. `IngredientItem.raw_line`
and `Ingredient.raw` both hold the source line verbatim, so a line that reached the
model but was carved into the wrong fields still matches itself here and is reported
by nothing in this module. Field-level damage is the completeness and linter passes'
job; this pass only asks whether the text arrived at all.

The audit is deliberately coarse. It normalizes both sides hard - case, markdown
syntax, list markers, whitespace - and then asks two questions of each content-bearing
source line: are its substantial words present in the parsed recipe, and are they still
next to each other? Word adjacency is what separates "the parser re-joined this prose"
from "a different sentence happens to use the same vocabulary". A line that answers
"no" is content the reader wrote and the reader will not get back. Because the
comparison is heuristic rather than a real round-trip, findings are WARNINGs: they are
strong evidence of loss, not proof of it.
"""

import re
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple

from recipe_parser.models.schemas import Recipe
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Diagnostic
from recipe_parser.validation.diagnostics import Severity

# Fraction of a line's substantial words that must be present for it to count as
# surviving. Prose gets reflowed and re-joined by the parser, so an exact substring
# match is too strict; requiring near-total word coverage keeps the slack small.
TOKEN_COVERAGE_THRESHOLD = 0.85

# Fraction of a line's adjacent word *pairs* that must still be adjacent somewhere in
# the parsed output. Word coverage alone is order-blind: a rewritten or reordered line
# scores nearly full marks against an unrelated sentence built from the same words.
# Substituting a single word in an eleven-word line breaks two pairs, which is enough
# to fall below this and be reported.
SEQUENCE_COVERAGE_THRESHOLD = 0.85

# Words shorter than this carry no evidence - "of", "a", "to" appear in every document.
# CJK is exempt: it is written without spaces, so a two-character run is a whole word.
MIN_TOKEN_LENGTH = 3

# Dropped lines this close together are reported as one finding rather than several.
# One blank line inside a run of dropped content (a code block, a quoted aside) should
# not split it into two diagnostics.
RUN_GAP_TOLERANCE = 2

# Model fields that describe structure rather than authored text. Including them would
# let a line match against the parser's own vocabulary ("ingredients", "directions").
STRUCTURAL_KEYS = frozenset({
    "block_type",
    "section_type",
    "component",
    "source_file",
    "unit_class",
})

# --- intentional drops -----------------------------------------------------------------
# Lines below are removed by design, not by accident, and must never be reported.
# They are tested against the line's *content*, after any list, step or heading marker
# has been stripped: `* [//]: # (nan's card)` is as intentional as the bare form.

# `[//]: # (a note to self)` - the markdown comment hack, stripped by
# strip_html_and_markdown_comments. Mirrored here rather than imported so this audit
# stays independent of the sanitizer's internals. Note that the sanitizer tolerates the
# spaceless `[//]:#(...)` spelling, which is not a link reference definition and so is
# caught by nothing else here.
RE_MARKDOWN_COMMENT = re.compile(r"^\[//\]:\s*#\s*\(.*\)$")

# `<!-- ... -->`, including the multi-line form.
RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# `[label]: https://example.com "title"` - a link reference definition, which markdown
# resolves into the referring link rather than rendering on its own.
RE_LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s+\S+")

# `* optional:` heading an indented sub-list. The parser folds the header away and sets
# optional=True on each child instead, so the word itself is absorbed rather than lost.
# It only does so when the item actually heads a sub-list, so this is checked against
# the following lines rather than applied to every `optional:` in the document.
RE_OPTIONAL_GROUP_HEADER = re.compile(r"^(?:[-*+]|\d+[.)])?\s*optional\s*:?$", re.IGNORECASE)

# --- source line shapes ----------------------------------------------------------------

RE_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
RE_HEADING_HASHES = re.compile(r"^#+\s*")
RE_QUOTE_MARKER = re.compile(r"^>\s?")

# The cell separators of a GFM table row. A row is stored in the model as its bare
# cells, so the pipes have to come off here too - otherwise a row whose cells are all
# too short to tokenize (`| 3x | 7" | 8" |`) falls through to the literal-character
# test and can never match, because the model side never contains a pipe.
RE_TABLE_ROW_PIPES = re.compile(r"\s*\|\s*")
RE_FENCE = re.compile(r"^\s*(?:```|~~~)")
RE_INDENTED_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+\S")

# `***`, `---`, `___` - a thematic break carries no text of its own, but a break
# followed by an H1 is how this corpus separates one recipe from the next, and that
# boundary is what lets a line be audited against its own recipe.
RE_THEMATIC_BREAK = re.compile(r"^(?:\*\s*){3,}$|^(?:-\s*){3,}$|^(?:_\s*){3,}$")

# An H1 - `#` followed by a space or by nothing at all.
RE_H1 = re.compile(r"^#(?:\s|$)")

# python-frontmatter's own boundary (`YAMLHandler.FM_BOUNDARY`). Three dashes is the
# common spelling but four or more open a frontmatter block just as well, and `...`
# does not close one. Diverging from the library in either direction means auditing
# YAML as if it were prose, or skipping prose as if it were YAML.
RE_FRONTMATTER_BOUNDARY = re.compile(r"^-{3,}\s*$")

# --- normalization ---------------------------------------------------------------------

RE_SYNTAX_CHARS = re.compile(r"[*_`~#>|\\-]")
# Everything that is not a word character (any script, so Japanese and Korean survive)
# or part of a number, URL or contraction. This is what erases `<`, `>`, `[`, `]`,
# `!` and `=`, and with them the difference between a bare URL and an autolink, or
# between `[label](target)` and `label target`.
RE_NOISE = re.compile(r"[^\w./:%'\"()]+", re.UNICODE)
RE_SPACES = re.compile(r"\s+")

# Punctuation that can cling to either end of a word without changing it. The parser
# rstrips ":" off every heading it reads, so `## Ingredients:` must tokenize exactly
# like the heading text it produces.
EDGE_PUNCTUATION = ".,:;'\"()"

# Scripts written without spaces, where a short run is still a whole word.
RE_UNSPACED_SCRIPT = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]"
)

# A line made of nothing but markdown punctuation - `---`, `___`, `|:--|--:|`, `>`.
# There is no authored text in it to lose, so it is not evidence of anything. Code
# fences (``` and ~~~) are deliberately absent: they delimit a block this parser
# always discards, so they are content-bearing evidence of exactly that.
RE_STRUCTURE_ONLY = re.compile(r"^[\s*_#>|<+=.,;:!?'\"()\[\]{}/\\-]*$")


def normalize(text: str) -> str:
    """
    Reduces a fragment of markdown to the bare words and numbers it asserts.

    Both sides of the comparison go through this, so it only has to erase the
    difference between a source line and the parser's rendering of it - markdown
    punctuation, case and whitespace - not to produce anything readable.
    """
    text = text.lower()
    text = RE_SYNTAX_CHARS.sub(" ", text)
    text = RE_NOISE.sub(" ", text)
    return RE_SPACES.sub(" ", text).strip()


def tokenize(normalized: str) -> List[str]:
    """
    The substantial words of a normalized fragment, in order.

    Short words are dropped from both sides alike: they are present in every document,
    so counting them as matches would let any line pass. Runs of an unspaced script are
    kept whatever their length, because a two-character run of kanji is a whole word.
    """
    tokens: List[str] = []
    for word in normalized.split():
        token = word.strip(EDGE_PUNCTUATION)
        if not token:
            continue
        if len(token) >= MIN_TOKEN_LENGTH or RE_UNSPACED_SCRIPT.search(token):
            tokens.append(token)
    return tokens


def collapse(text: str) -> str:
    """Lowercases and squeezes whitespace, keeping every other character."""
    return RE_SPACES.sub(" ", text.lower()).strip()


class ParsedIndex:
    """
    What a set of recipes says, in the three shapes this audit asks about.

    `tokens` answers "is this word anywhere in the output", `bigrams` answers "are these
    two words still next to each other", and `verbatim` is the untouched text, used for
    lines that hold no word long enough to be evidence - a fraction, a temperature
    tolerance - where the only honest test is whether the characters are still there.
    """

    __slots__ = ("tokens", "bigrams", "verbatim")

    def __init__(self, chunks: Sequence[str]) -> None:
        joined = " ".join(chunks)
        words = tokenize(normalize(joined))
        self.tokens: Set[str] = set(words)
        self.bigrams: Set[Tuple[str, str]] = set(zip(words, words[1:]))
        self.verbatim: str = collapse(joined)


def _collect_strings(node: Any, sink: List[str]) -> None:
    """Walks a dumped model and gathers every authored string it holds."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in STRUCTURAL_KEYS:
                continue
            _collect_strings(value, sink)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_strings(value, sink)
    elif isinstance(node, str):
        sink.append(node)


def _strings_of(recipe: Recipe) -> List[str]:
    chunks: List[str] = []
    dumped = (
        recipe.model_dump(by_alias=True) if hasattr(recipe, "model_dump")
        else recipe.dict(by_alias=True)
    )
    _collect_strings(dumped, chunks)
    return chunks


def build_parsed_index(recipes: Iterable[Recipe]) -> ParsedIndex:
    """Indexes every authored string in the given recipes."""
    chunks: List[str] = []
    for recipe in recipes:
        chunks.extend(_strings_of(recipe))
    return ParsedIndex(chunks)


def _strip_frontmatter(lines: Sequence[str]) -> int:
    """
    Returns the index of the first line after any YAML frontmatter block.

    Frontmatter is metadata, kept on the document rather than inside a recipe, so it is
    outside what this audit is asking about. The block is recognised exactly as
    python-frontmatter recognises it, because that is what decided whether the parser
    ever saw these lines: `-{3,}` opens and closes it, leading blank lines are ignored
    (the library strips the text first), and `...` closes nothing.
    """
    first = 0
    while first < len(lines) and not lines[first].strip():
        first += 1
    if first >= len(lines) or not RE_FRONTMATTER_BOUNDARY.match(lines[first].strip()):
        return 0
    for index in range(first + 1, len(lines)):
        if RE_FRONTMATTER_BOUNDARY.match(lines[index].strip()):
            return index + 1
    # No closing boundary: the library hands the whole file back as content.
    return 0


def _heads_a_sub_list(lines: Sequence[str], offset: int) -> bool:
    """
    Whether the list item at `offset` introduces an indented sub-list.

    This is the condition under which the parser absorbs an `optional:` header rather
    than keeping it as an item, so it is the condition under which the header's
    disappearance is by design.
    """
    own = RE_INDENTED_LIST_ITEM.match(lines[offset])
    if not own:
        return False
    own_indent = len(own.group(1))
    for index in range(offset + 1, len(lines)):
        if not lines[index].strip():
            continue
        nested = RE_INDENTED_LIST_ITEM.match(lines[index])
        return bool(nested) and len(nested.group(1)) > own_indent
    return False


def _is_intentionally_dropped(content: str, lines: Sequence[str], offset: int) -> bool:
    """True for source lines the parser is designed to discard."""
    if RE_MARKDOWN_COMMENT.match(content):
        return True
    if RE_LINK_DEFINITION.match(content):
        return True
    if RE_OPTIONAL_GROUP_HEADER.match(lines[offset].strip()) and _heads_a_sub_list(lines, offset):
        return True
    return False


def _content_of(stripped: str) -> str:
    """Removes the markers that position a line, leaving only what it says."""
    content = RE_LIST_MARKER.sub("", stripped)
    content = RE_HEADING_HASHES.sub("", content)
    content = RE_QUOTE_MARKER.sub("", content)
    content = RE_TABLE_ROW_PIPES.sub(" ", content)
    return content


def _survived(content: str, index: ParsedIndex) -> bool:
    """
    Whether a source line's content is represented in the parsed output.

    Prose the parser re-joined across line breaks is accepted when nearly all of its
    substantial words are present *and* nearly all of them are still adjacent. A line
    with no substantial words is judged on its literal characters instead, so that a
    dropped `1/2 -> 1/4` or `50 C +/- 2` is not waved through for lack of vocabulary.
    """
    tokens = tokenize(normalize(content))
    if tokens:
        hits = sum(1 for token in tokens if token in index.tokens)
        if (hits / len(tokens)) < TOKEN_COVERAGE_THRESHOLD:
            return False
        pairs = list(zip(tokens, tokens[1:]))
        if pairs:
            adjacent = sum(1 for pair in pairs if pair in index.bigrams)
            if (adjacent / len(pairs)) < SEQUENCE_COVERAGE_THRESHOLD:
                return False
        return True

    residue = collapse(content)
    if not residue or RE_STRUCTURE_ONLY.match(residue):
        # Markdown punctuation and nothing else. There is no authored text here to
        # lose, so this is not evidence either way.
        return True
    return residue in index.verbatim


def _next_block_is_a_title(lines: Sequence[str], offset: int) -> bool:
    """Whether the next thing after `offset` that markdown would tokenize is an H1."""
    for index in range(offset, len(lines)):
        stripped = lines[index].strip()
        if not stripped or RE_THEMATIC_BREAK.match(stripped):
            continue
        return bool(RE_H1.match(stripped))
    return False


def _has_content(lines: Sequence[str], start: int, end: int) -> bool:
    return any(
        stripped and not RE_THEMATIC_BREAK.match(stripped)
        for stripped in (line.strip() for line in lines[start:end])
    )


def recipe_line_spans(
        lines: Sequence[str],
        start: int,
        recipe_count: int,
) -> Optional[List[Tuple[int, int]]]:
    """
    One `(start, end)` line span per parsed recipe, or None if they cannot be matched up.

    Multi-recipe files are ordinary here, and a single flattened haystack lets text in
    recipe A vouch for content lost from recipe B - which is precisely the loss this
    audit exists to see. The parser starts a new recipe at a thematic break that
    introduces an H1 (`split_sub_recipes_into_raw_runs`), so the same rule is applied to
    the raw lines. If the number of spans found does not match the number of recipes
    parsed, the reconstruction is wrong somewhere and attribution is abandoned rather
    than guessed at.
    """
    if recipe_count <= 1:
        return None

    starts = [start]
    in_fence = False
    for index in range(start, len(lines)):
        line = lines[index]
        if RE_FENCE.match(line):
            # A `---` inside a code block is text, not a break.
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if not RE_THEMATIC_BREAK.match(stripped):
            continue
        if not _next_block_is_a_title(lines, index + 1):
            continue
        if _has_content(lines, starts[-1], index):
            starts.append(index)

    if len(starts) != recipe_count:
        return None
    return list(zip(starts, starts[1:] + [len(lines)]))


def _scan(recipes: Sequence[Recipe], source_text: str) -> List[Tuple[int, str, Optional[str]]]:
    """`(line_number, raw_line, recipe_title)` for every source line that left no trace."""
    if not source_text:
        return []

    # Blank out HTML comments in place so line numbers stay true to the file.
    masked = RE_HTML_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), source_text)
    # split("\n") rather than splitlines(): the latter also breaks on form feeds, NEL and
    # the Unicode line/paragraph separators, which shifts every line number after one.
    lines = masked.split("\n")
    first = _strip_frontmatter(lines)

    spans = recipe_line_spans(lines, first, len(recipes))
    indexes: List[Tuple[int, int, ParsedIndex, Optional[str]]] = []
    if spans is None:
        title = recipes[0].title if len(recipes) == 1 else None
        indexes.append((first, len(lines), build_parsed_index(recipes), title))
    else:
        for recipe, (span_start, span_end) in zip(recipes, spans):
            indexes.append((span_start, span_end, ParsedIndex(_strings_of(recipe)), recipe.title))

    dropped: List[Tuple[int, str, Optional[str]]] = []
    for span_start, span_end, index, title in indexes:
        for offset in range(max(span_start, first), span_end):
            raw = lines[offset]
            stripped = raw.strip()
            if not stripped:
                continue
            content = _content_of(stripped)
            if _is_intentionally_dropped(content, lines, offset):
                continue
            if not _survived(content, index):
                dropped.append((offset + 1, raw.rstrip(), title))

    return dropped


def find_dropped_source_lines(recipes: Sequence[Recipe], source_text: str) -> List[Tuple[int, str]]:
    """
    Returns `(line_number, raw_line)` for every content-bearing source line that left no
    trace in the parsed recipes. Exposed separately so it can be tested and reused
    without going through diagnostic construction.
    """
    return [(number, text) for number, text, _ in _scan(recipes, source_text)]


def _group_into_runs(
        dropped: Sequence[Tuple[int, str, Optional[str]]],
) -> List[List[Tuple[int, str, Optional[str]]]]:
    """Collapses neighbouring dropped lines into one run so a lost block reports once."""
    runs: List[List[Tuple[int, str, Optional[str]]]] = []
    for entry in dropped:
        previous = runs[-1][-1] if runs else None
        if (
                previous is not None
                and previous[2] == entry[2]
                and entry[0] - previous[0] <= RUN_GAP_TOLERANCE
        ):
            runs[-1].append(entry)
        else:
            runs.append([entry])
    return runs


def audit_source_coverage(
        recipes: Sequence[Recipe],
        source_text: str,
        max_detail_lines: int = 12,
) -> List[Diagnostic]:
    """
    Reports source content that never reached the parsed model.

    Emits one WARNING per contiguous run of dropped lines. WARNING rather than ERROR
    because the comparison is a similarity test, not a real round-trip: a line can be
    reported while a heavily reworded version of it did in fact survive. Every finding
    still names the exact line and quotes the text, so a false one is cheap to dismiss.
    """
    dropped = _scan(recipes, source_text)
    if not dropped:
        return []

    diagnostics: List[Diagnostic] = []
    for run in _group_into_runs(dropped):
        first_line, first_text, title = run[0]
        span = (
            f"line {first_line}" if len(run) == 1
            else f"lines {first_line}-{run[-1][0]}"
        )
        detail = [f"line {number}: {text.strip()!r}" for number, text, _ in run[1:max_detail_lines + 1]]
        if len(run) - 1 > len(detail):
            detail.append(f"... and {len(run) - 1 - len(detail)} more line(s)")

        diagnostics.append(Diagnostic(
            severity=Severity.WARNING,
            code=Code.SOURCE_CONTENT_DROPPED,
            recipe=title,
            line_number=first_line,
            context=first_text,
            message=(
                f"{len(run)} source line(s) at {span} produced nothing in the parsed "
                f"output. This content is silently lost: either the parser has no home "
                f"for it, or it should be rewritten in a form the parser reads."
            ),
            detail=detail,
        ))

    return diagnostics
