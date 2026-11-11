"""
The Claude gateway: every Claude call in LANSH goes through this package (plan §8.2).

``request`` defines what is sent and the hash that keys its recorded answer, ``backend`` runs
one ``claude -p`` call, ``cassette`` stores the recorded answers and ``errors`` holds the
exceptions. ``gateway`` ties them together: it replays or calls live by mode, re-checks each
answer with Pydantic and caps the number of live calls.
"""
