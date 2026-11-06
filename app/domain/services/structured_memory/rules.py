"""
Rule engine skeleton (v1) — ordered rules, explainable ``rule_id``.

Aligned with §3a ideas: NFKC + case-insensitive substring checks on normalized
text; extend with locale-specific regex later.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    memory_category: str
    confidence: float
    memory_text: str  # canonical snippet stored on extracted_memory


def _norm_for_match(text: str) -> str:
    # casefold() > lower() for Turkish/Unicode case-insensitive use with regex
    return unicodedata.normalize("NFKC", (text or "")).casefold()


# (rule_id, category, confidence, compiled_pattern, human_snippet_group)
# Order: explicit / high-signal patterns first; broader patterns later.
# Text is NFKC + casefolded before matching (see ``_norm_for_match``).
_RULES: List[tuple] = [
    # --- Turkish (tr) — explicit memory / format / language ---
    (
        "tr_remember_hatirla_v1",
        "user_preference",
        0.81,
        re.compile(
            r"((?:şunu\s+)?(?:hatırla|unutma)\s*[:/]\s*[^.!?\n…]{2,120})",
        ),
        1,
    ),
    (
        "tr_user_preference_tercihim_v1",
        "user_preference",
        0.77,
        re.compile(
            r"(tercihim\s*[:/]\s*[^.!?\n…]{2,120})",
        ),
        1,
    ),
    (
        "tr_user_preference_tercih_ediyorum_v1",
        "user_preference",
        0.76,
        re.compile(
            r"((?:.{0,40})?tercih\s+ediyorum[^.!?\n…]{0,120})",
            re.DOTALL,
        ),
        1,
    ),
    (
        "tr_user_preference_kullanmayi_tercih_v1",
        "user_preference",
        0.75,
        re.compile(
            r"(\S+(?:\s+\S+){0,12}\s+kullanmay[ıi]\s+tercih\s+ederim)",
        ),
        1,
    ),
    (
        "tr_language_turkce_v1",
        "user_preference",
        0.79,
        re.compile(
            r"((?:türkçe\s+(?:cevap(?:la|lar)?\s+ver|konuş|yaz)|yanıt(?:ları|larımızı)?\s+türkçe|cevap(?:ları)?\s+türkçe\s+olsun))",
        ),
        1,
    ),
    (
        "tr_from_now_on_v1",
        "user_preference",
        0.74,
        re.compile(
            r"((?:bundan\s+sonra)\s+[^.!?\n…]{3,80}(?:ver|kullan|yaz|ekle|olsun|tercih\s+et))",
        ),
        1,
    ),
    (
        "tr_always_v1",
        "user_preference",
        0.71,
        re.compile(
            r"((?:her\s+zaman)\s+[^.!?\n…]{3,80}(?:ver|kullan|yaz|olsun|tercih))",
        ),
        1,
    ),
    (
        "tr_format_brief_v1",
        "user_preference",
        0.72,
        re.compile(
            r"((?:kısa\s+cevap(?:lar)?\s+ver|özetle(?:r\s+misin)?|maddeler\s+halinde\s+(?:yaz|ver)|tek\s+cümle(?:de)?\s+(?:cevap|yanıt)))",
        ),
        1,
    ),
    (
        "tr_code_examples_v1",
        "user_preference",
        0.72,
        re.compile(
            r"((?:kod\s+örnek(?:leri|i)?\s+(?:ver|ekle|göster)|örnek\s+kod\s+(?:ver|göster)))",
        ),
        1,
    ),
    (
        "tr_user_constraint_v1",
        "user_constraint",
        0.8,
        re.compile(
            r"((?:asla|sakın|kesinlikle|bir\s+daha)\s+.{0,40}?(?:yapma|kullanma|ekleme|yazma|etme|bırak)[^.!?\n…]{0,100})",
        ),
        1,
    ),
    (
        "tr_user_constraint_olmasin_v1",
        "user_constraint",
        0.78,
        re.compile(
            r"([^.\n!？]{0,100}(?:şifre|anahtar|api\s*key|token)[^.!?\n…]{0,30}(?:saklama|koyma|gösterme|paylaşma|olmasın))",
        ),
        1,
    ),
    (
        "tr_no_emoji_v1",
        "user_constraint",
        0.77,
        re.compile(
            r"((?:emoji\s+kullanma|emoji\s+ekleme))",
        ),
        1,
    ),
    (
        "tr_no_markdown_v1",
        "user_constraint",
        0.76,
        re.compile(
            r"((?:markdown\s+kullanma|markdown\s+formatında\s+yazma))",
        ),
        1,
    ),
    (
        "tr_project_decision_v1",
        "project_decision",
        0.73,
        re.compile(
            r"((?:karar\s+(?:verdik|aldık)|böyle\s+kararlaştık|anlaştık\s+ki|şu\s+konuda\s+anlaştık)\s*[^.!?\n…]{0,200})",
        ),
        1,
    ),
    (
        "tr_resolved_issue_v1",
        "resolved_issue",
        0.75,
        re.compile(
            r"((?:çözüldü|sorun\s+çözüldü|hata\s+giderildi)\s*[:/]?\s*[^.!?\n…]{0,120})",
        ),
        1,
    ),
    # --- English (en) ---
    (
        "en_remember_v1",
        "user_preference",
        0.8,
        re.compile(
            r"((?:remember|keep\s+in\s+mind)\s*[:/]\s*[^.!?\n]{2,120})",
        ),
        1,
    ),
    (
        "rx_user_preference_v1",
        "user_preference",
        0.78,
        re.compile(
            r"\b(i\s+(?:prefer|would\s+rather|always)\s+[^.!?]{3,120})",
            re.DOTALL,
        ),
        1,
    ),
    (
        "en_be_concise_v1",
        "user_preference",
        0.74,
        re.compile(
            r"((?:be\s+concise|keep\s+(?:your\s+)?answers?\s+short|answer\s+briefly))",
        ),
        1,
    ),
    (
        "en_respond_in_language_v1",
        "user_preference",
        0.77,
        re.compile(
            r"((?:respond|reply|answer)\s+in\s+(?:turkish|english|german|french|spanish)[^.!?\n]{0,40})",
        ),
        1,
    ),
    (
        "en_from_now_on_v1",
        "user_preference",
        0.73,
        re.compile(
            r"((?:from\s+now\s+on)\s+[^.!?\n]{3,120})",
        ),
        1,
    ),
    (
        "rx_user_constraint_v1",
        "user_constraint",
        0.82,
        re.compile(
            r"\b((?:do\s+not|never|must\s+not)\s+[^.!?]{3,120})",
            re.DOTALL,
        ),
        1,
    ),
    (
        "en_no_emoji_v1",
        "user_constraint",
        0.76,
        re.compile(
            r"((?:don't|do\s+not)\s+use\s+emojis?)",
        ),
        1,
    ),
    (
        "rx_project_decision_v1",
        "project_decision",
        0.74,
        re.compile(
            r"\b((?:we\s+decided|decision\s+is|agreed\s+to)\s+[^.!?]{3,120})",
            re.DOTALL,
        ),
        1,
    ),
    (
        "en_resolved_issue_v1",
        "resolved_issue",
        0.74,
        re.compile(
            r"((?:fixed|resolved)\s*[:/]?\s*[^.!?\n]{0,120})",
        ),
        1,
    ),
]


def evaluate_rules(message_content: str) -> Optional[RuleHit]:
    """First matching rule wins (priority = declaration order)."""
    blob = _norm_for_match(message_content)
    for rule_id, category, conf, rx, grp in _RULES:
        m = rx.search(blob)
        if not m:
            continue
        snippet = m.group(grp).strip()
        if len(snippet) < 3:
            continue
        snippet = snippet[:500]
        return RuleHit(
            rule_id=rule_id,
            memory_category=category,
            confidence=conf,
            memory_text=snippet,
        )
    return None

