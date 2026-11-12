"""
Discover (plan §8.3): what each legacy job reads and writes, its lineage, traps and waves.

``split`` cuts the code into blocks, ``traps`` holds the trap library and the two-pass trap
scan, ``lineage`` the Lineage agent with its verification and sqlglot cross-check, ``job``
runs all of them for one job, and ``estate`` builds the estate's DAG, waves and the flows of
tagged columns.
"""
