# Insurance Claims SOP Agent

A conversational insurance claims support agent that follows a fixed four-phase SOP
(`VERIFY_ID -> RESOLVE_INTENT -> PROCESS_CASE -> POST_PROCESS`) while still talking naturally.
Deterministic code controls the workflow and safety gates; the LLM interprets language and phrases replies.

> All customer, policy, claim and PII data in this repository is synthetic test data.

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
