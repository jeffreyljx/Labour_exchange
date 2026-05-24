"""
Mock credit bureau integration.

In production, replace fetch_credit_score with a real API call to
Equifax, Experian, or TransUnion using the user's full SSN + identity data.
The interface contract (ssn_last4 -> int score) stays the same.
"""
import random


def fetch_credit_score(ssn_last4: str) -> int:
    """Return a deterministic mock FICO score (300–850) seeded by ssn_last4.

    Deterministic so the same SSN always returns the same score in tests.
    Known test values:
      0000 -> 694  (APPROVED — use this for happy-path tests)
      1234 -> 567  (REJECTED — use this to test credit-denial flow)
      9999 -> 332  (REJECTED)
    """
    seed = int(ssn_last4) * 7919  # prime multiplier for spread
    rng = random.Random(seed)
    return rng.randint(300, 850)
