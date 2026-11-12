"""
Generate (plan §8.5, §8.7): turn a legacy job into a migrated PySpark module, safely.

``template`` defines the job template every migrated job follows, ``draft`` the deterministic
sqlglot draft, ``translator`` the Claude translation, ``guardrails`` the checks that run before
any generated code executes, ``worker`` the isolated process that runs it, and ``testgen``
the trap-focused tests with expected values from the legacy engine.
"""
