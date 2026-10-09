"""Operational workers.

Not required to run the platform. Analyses execute synchronously in a few
seconds; these exist for when volume makes that untenable.

    python -m workers.analysis_worker

The design reason this is separable is that no agent performs a calculation.
Dropping the agent step changes how long an analysis takes; it does not change
any figure in the result.
"""