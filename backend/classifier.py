"""Rule-based classifier for hidden text.

Swap `classify` for an LLM judge later: keep the same signature
(text, technique) -> (classification, reason_suffix).
"""
import re

from invisible import count_invisible, decode_tag_chars

MANIPULATION_PATTERNS = [
    r"ignore (all )?(previous|prior|above)",
    r"ignore all",
    r"disregard (all |the )?(previous|prior|above)",
    r"\byou are\b",
    r"as an ai",
    r"language model",
    r"\bllms?\b",
    r"\bai (screener|reviewer|assistant|model)",
    r"note to ai",
    r"\breviewers?\b",
    r"positive review",
    r"recommend accept",
    r"recommend(ing)? (this|the) (paper|candidate)",
    r"rate this",
    r"rank (them|this|him|her) (first|highest|top)",
    r"hire this candidate",
    r"best candidate",
    r"most qualified",
    r"highly qualified",
    r"do not mention",
    r"don't mention",
    r"system prompt",
    r"new instructions",
]

# Hidden text that talks to the classifier/scanner itself is an attack on the detection
# pipeline, so it is always "manipulation" -- including attempts to fake our LLM prompt's delimiters.
CLASSIFIER_ADDRESSING_PATTERNS = [
    # Phrased as *addressing* a detector, so ordinary topic words ("document classification") don't fire.
    r"\b(note to|attention|dear|to) (any |the |all )?(ai |automated )?(classifier|scanner|detector)s?\b",
    r"\b(ai|llm|automated) (classifier|scanner|detector)s?\b",
    r"\bclassify (this|it|them|everything|all|me|as)\b",
    r"\blabel (this|it|them|everything|all|as)\b",
    r"\boutput (the )?label",
    r"\bmark (this|it) as\b",
    r"\b(this|it) is (benign|safe|harmless|not malicious)\b",
    r"\bnot (a )?prompt injection",
    r"\bignore (your|the) (instructions|rules|system)",
    r"</?\s*snippet",
    r"\bsystem\s*:",
]

ACCESSIBILITY_HINTS = ["alt text", "image of", "figure", "logo", "decorative", "page ", "header", "footer"]

SEVERITY = {"benign": 0, "suspicious": 1, "manipulation": 2}
LABELS = tuple(SEVERITY)


def max_severity(a: str, b: str | None) -> str:
    """Higher-severity label of the two; None (no second opinion) keeps `a`."""
    if b not in SEVERITY:
        return a
    return a if SEVERITY[a] >= SEVERITY[b] else b


def compute_risk(labels) -> str:
    worst = max((SEVERITY[l] for l in labels), default=0)
    return {0: "clean", 1: "suspicious", 2: "manipulation"}[worst]


MAX_BENIGN_INVISIBLE = 5  # a stray zero-width char or soft hyphen happens; more than this in one snippet doesn't


def classify_invisible(raw_text: str) -> tuple[str, str] | None:
    """Rule for invisible Unicode, run on the raw text (with the invisible chars still in it).
    Hidden tag-character text is an encoded message by construction; a dense cluster of zero-width
    chars is a watermark/fingerprint or a smuggled payload. Either way it's deliberate."""
    decoded = decode_tag_chars(raw_text)
    if decoded.strip():
        return "manipulation", f'Invisible tag characters encode hidden text ("{decoded[:80]}").'
    n = count_invisible(raw_text)
    if n > MAX_BENIGN_INVISIBLE:
        return "manipulation", f"{n} invisible characters in one snippet (more than {MAX_BENIGN_INVISIBLE})."
    return None


def classify(text: str, technique: str) -> tuple[str, str]:
    lowered = text.lower()
    for p in CLASSIFIER_ADDRESSING_PATTERNS:
        m = re.search(p, lowered)
        if m:
            return "manipulation", f'Hidden text addresses the classifier/scanner itself (matched "{m.group(0)}").'
    hits = [p for p in MANIPULATION_PATTERNS if re.search(p, lowered)]
    if hits:
        phrase = re.search(hits[0], lowered).group(0)
        return "manipulation", f'Contains AI-directed instruction language (matched "{phrase}").'

    words = re.findall(r"[a-zA-Z]{2,}", text)
    if any(h in lowered for h in ACCESSIBILITY_HINTS) and len(words) <= 8:
        return "benign", "Looks like an accessibility label or layout artifact."
    if len(words) <= 2 and technique != "invisible_unicode":
        return "benign", "Very short and non-instructional."
    return "suspicious", "Hidden content that a human reader would not see, but no explicit AI instructions detected."
