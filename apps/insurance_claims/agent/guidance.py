"""Which parts of the guideline knowledge base apply to a question. Pure code, no LLM.

Two jobs:

1. Document guidance. The claims name documents one way ("pathology report", "office note")
   and the guidelines another ("original pathology report", "treating provider office note"),
   and some documents ("diagnosis report") have no specific guidance at all. Names are matched
   by token containment, and the fallback chain is: the document's own guidance, then the claim
   type's guidance, then the default guidance. Nothing is ever invented to fill a gap.

2. Follow-up rules. A caller's question can touch several independent topics ("where do I
   upload it, and how long will it take?"). Candidates come from phrases in the question and
   from topics the LLM proposed. A rule applies only if the caller's intent and the claim
   allow it. When phrases overlap, the longest and most specific one wins ("how soon do I need
   to submit" beats "how soon"). Non-overlapping topics are all kept, each once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .fixtures import FollowupRule, Guidelines, localized

_STOPWORDS = frozenset({"the", "a", "an", "of", "for", "to", "and", "your", "my"})


def _tokens(text: str) -> frozenset[str]:
    """Lowercase word set with trivial plurals folded ("photos" and "photo" agree)."""
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", text.casefold()):
        if word in _STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        tokens.add(word)
    return frozenset(tokens)


# ---- document guidance ----------------------------------------------------------------


def match_document_key(doc: str, keys: Iterable[str]) -> str | None:
    """Find the guideline key for a document name, or None.

    A key whose words contain all of the document's words is the best match (fewest extra
    words wins). A key that is more generic than the document is a weaker match. If two keys
    tie, the answer is None: guessing between them could give the caller the wrong advice."""
    doc_tokens = _tokens(doc)
    if not doc_tokens:
        return None
    scored: list[tuple[int, str]] = []
    for key in sorted(keys):
        key_tokens = _tokens(key)
        if not key_tokens:
            continue
        if doc_tokens <= key_tokens:
            scored.append((len(key_tokens) - len(doc_tokens), key))
        elif key_tokens <= doc_tokens:
            scored.append((100 + len(doc_tokens) - len(key_tokens), key))
    if not scored:
        return None
    scored.sort()
    best = scored[0][0]
    winners = [key for score, key in scored if score == best]
    return winners[0] if len(winners) == 1 else None


@dataclass(frozen=True)
class GuidanceText:
    level: Literal["document", "case_type", "default"]
    key: str | None
    text: str


def document_guidance(
    doc: str, case_type: str | None, guidelines: Guidelines
) -> GuidanceText | None:
    """Guidance for one requested document: its own, else its claim type's, else the default."""
    key = match_document_key(doc, guidelines.document_guidance)
    if key is not None:
        text = localized(guidelines.document_guidance[key])
        if text:
            return GuidanceText("document", key, text)
    if case_type:
        by_type = {k.casefold(): k for k in guidelines.case_type_guidance}
        type_key = by_type.get(case_type.casefold())
        if type_key is not None:
            text = localized(guidelines.case_type_guidance[type_key])
            if text:
                return GuidanceText("case_type", type_key, text)
    text = localized(guidelines.default_guidance)
    return GuidanceText("default", None, text) if text else None


def alternative_guidance(doc: str, guidelines: Guidelines) -> GuidanceText | None:
    """What to try when the caller cannot get a requested document."""
    alternatives = guidelines.document_alternative_guidance
    key = match_document_key(doc, [k for k in alternatives if k != "default"])
    if key is not None:
        text = localized(alternatives[key])
        if text:
            return GuidanceText("document", key, text)
    text = localized(alternatives.get("default"))
    return GuidanceText("default", None, text) if text else None


# ---- follow-up rules ------------------------------------------------------------------


@dataclass(frozen=True)
class FollowupMatch:
    rule: FollowupRule
    via: Literal["phrase", "semantic"]
    phrase: str | None = None  # the phrase that matched, for phrase matches


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _eligible(rule: FollowupRule, intents: Sequence[str], has_documents: bool) -> bool:
    if rule.requires_documents and not has_documents:
        return False
    # With no intent known (for example the LLM is down) the phrase itself is the evidence.
    if rule.intent_hints and intents and not any(i in rule.intent_hints for i in intents):
        return False
    return True


def match_followups(
    rules: Sequence[FollowupRule],
    question: str,
    *,
    intents: Sequence[str] = (),
    topics: Sequence[str] = (),
    has_documents: bool,
) -> list[FollowupMatch]:
    """Select every follow-up rule that applies to the question, each at most once.

    Phrase matches come first, in the order they appear in the question; then topics proposed
    by the LLM that the phrases did not already cover. A topic whose only phrase was beaten by
    a longer, overlapping phrase stays out, even if the LLM proposed it."""
    text = _normalize(question)
    eligible = [rule for rule in rules if _eligible(rule, intents, has_documents)]

    found: list[tuple[int, int, FollowupRule, str]] = []
    for rule in eligible:
        best: tuple[int, int, str] | None = None
        for phrase in rule.match_any:
            needle = _normalize(phrase)
            if not needle:
                continue
            pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
            for hit in re.finditer(pattern, text):
                if best is None or hit.end() - hit.start() > best[1] - best[0]:
                    best = (hit.start(), hit.end(), phrase)
        if best is not None:
            found.append((best[0], best[1], rule, best[2]))

    accepted: list[tuple[int, int, FollowupRule, str]] = []
    rejected: set[str] = set()
    for start, end, rule, phrase in sorted(found, key=lambda f: (-(f[1] - f[0]), f[0])):
        if all(end <= s or start >= e for s, e, _, _ in accepted):
            accepted.append((start, end, rule, phrase))
        else:
            rejected.add(rule.topic)

    matches = [
        FollowupMatch(rule, "phrase", phrase)
        for _, _, rule, phrase in sorted(accepted, key=lambda a: a[0])
    ]
    covered = {m.rule.topic for m in matches} | rejected
    by_topic = {rule.topic: rule for rule in eligible}
    for topic in topics:
        if topic in by_topic and topic not in covered:
            matches.append(FollowupMatch(by_topic[topic], "semantic"))
            covered.add(topic)
    return matches


class _Missing(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill_template(template: str, values: Mapping[str, str]) -> str:
    """Fill {placeholders}. A placeholder with no value is left visible, never guessed."""
    try:
        return template.format_map(_Missing(values))
    except (ValueError, IndexError):
        return template
