"""Bid Intelligence analysis engine (dual-analyst, evidence-register based).

Pipeline (engine/pipeline.py):
  source package (package.py) -> independent extraction by two analysts
  (extraction.py, providers.py) -> quote/value verification (verify.py) ->
  evidence register and reconciliation (register.py) -> bounded adjudication
  (adjudicate.py) -> conflicts, clarifications and amendments (conflicts.py)
  -> FAST / FULL composition with an omission ledger (reports.py) ->
  pre-publication review (review.py) -> PDF (render.py).

Release-blocking constraints: docs/current/ENGINE_REBUILD_CONSTRAINTS.md.
Every package is interpreted only from its own documents; the engine holds no
buyer-, document- or test-specific rules and reads no memory or other
tenant's data.
"""

ENGINE_VERSION = "engine-1.0"
