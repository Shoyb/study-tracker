# Rules for AI assistants working on Study Tracker

- Read docs/PLAN.md sections D (database), E (timer) and G (statistics)
  before changing related code. The plan is the specification.
- Work on ONE milestone at a time. Do not implement later milestones.
- Layering: core <- domain <- db <- services <- ui. charts imports only
  core and domain. Never import upward. No SQL outside db/. No Qt in
  core, domain, db, services or charts.
- Timestamps are UTC ISO 8601 strings ending in Z. Durations are integer
  seconds. Get "now" only from the injected Clock, never datetime.now().
- Never edit an applied migration; add a new numbered one.
- Every business rule needs a pytest test. Run pytest and ruff check
  before saying a step is done.
- Do not add a dependency without asking first.
- No base classes, plugin systems or extra abstractions unless asked.
- Keep files small and diffs small. Explain each change in plain words.
- If a requirement is ambiguous, state a recommended default and ask.
