# Follow-up recent_document — suite + real-model UAT

Base HEAD before fix: `acc4ead`. UX WIP untouched / not staged.

## Suite

`NATIVE_FLOW_A00_TEST=1 pytest` → **178+ passed** (includes `tests/test_recent_document_context.py`).

## Real model (qwen3.5:9b, GPU; no DB writes)

Fixture: `05_multipage_cross_reference` content has no telefon/phone (`FIXTURE_PHONE_ABSENT`).

| Case | Result |
| --- | --- |
| Standard: open 05 → “Bu belgedeki müşterinin telefon numarası nedir?” | ANSWER; no CLARIFY; cites `05_….docx`; phone absent |
| document-review: same | ANSWER; `file_read`; no CLARIFY; phone absent |
| A(05)→B(06) → “bu belgedeki sevkiyat…” | ANSWER about **06**; not A |
| Empty session + phone question | CLARIFY |

Sahip UAT / merge / A05: yok.
