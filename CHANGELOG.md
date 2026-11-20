# Changelog

## 0.1.0 - 2026-11-20

- First release.
- 70 scenarios across 6 channels (Instagram, WhatsApp, Messenger, Telegram, X, live chat), 7 languages and 10 categories.
- Deterministic checks: required and forbidden patterns, reply language, length per channel, plain-text formatting, handoff marker.
- Optional LLM judge with a published rubric, reported separately.
- `dm-bench run`, `report`, `validate` and `list`; any OpenAI-compatible endpoint, your own agent over HTTP, or offline mocks.
