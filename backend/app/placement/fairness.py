"""Fairness guard rails for placement scoring.

The scoring model is explicit, so fairness is checkable rather than asserted:
only the features below feed a suitability score, and a protected attribute may
never appear among them. ``assert_no_protected_attributes`` is called at import
time and by a test, so adding a protected feature to scoring fails loudly.
"""

from __future__ import annotations

# Attributes that reflect who a student is rather than what they can do. None of
# these may enter a score. The AMYPO schema does not store them, and this list is
# the tripwire that keeps it that way.
PROTECTED_ATTRIBUTES = frozenset(
    {
        "gender", "sex", "caste", "religion", "community", "race", "ethnicity",
        "marital_status", "disability", "age", "date_of_birth", "dob", "region",
        "language", "mother_tongue", "nationality", "socioeconomic_status",
        "family_income", "parent_occupation",
    }
)


def assert_no_protected_attributes(feature_names) -> None:
    """Raise if any scoring feature is a protected attribute."""
    offending = sorted(name for name in feature_names if name in PROTECTED_ATTRIBUTES)
    if offending:
        raise ValueError(f"protected attribute(s) in scoring: {', '.join(offending)}")
