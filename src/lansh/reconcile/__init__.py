"""
Reconcile and heal (plan §8.6): prove a migrated output matches its legacy output.

``engine`` compares two DataFrames record for record under each column's comparison policy
and builds the contract's ``ReconReport``. ``signatures`` recognises the patterns known traps
leave in a failed comparison, and ``heal`` runs the diagnose-patch-rerun loop.
"""
