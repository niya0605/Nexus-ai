"""Authentication cookie names — the one place both the endpoint layer
(which sets/clears them) and the auth dependency (which reads them)
get these from, so the two can never drift apart.

Names/attributes established in S1C.2; S1D reuses them unchanged per
its own instructions ("Do not change the existing cookie names or
SameSite choice unless there is a demonstrated defect").
"""

ACCESS_TOKEN_COOKIE = "nexus_access_token"
REFRESH_TOKEN_COOKIE = "nexus_refresh_token"
