"""TEX operations: system status, alerts (ADR-047).

``checks`` is pure (no frappe import): thresholds, verdicts, transitions and alert text.
``status`` gathers the numbers from the database, ``alerts`` is the scheduled notifier.
"""
