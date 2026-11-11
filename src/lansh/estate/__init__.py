"""
The legacy estate: synthetic data, the job inventory, golden outputs and their checks.

Some of it is evaluation tooling: ``labels``, ``holdout`` and the answer-key checks in
``runner`` and ``golden_sas`` read ``estate/labels/`` or ``estate/holdout/``, so factory code
must never call them.
"""
