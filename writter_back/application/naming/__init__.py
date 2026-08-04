"""Classical-source naming infrastructure."""

from application.naming.models import (
    NameCandidate,
    NameSelection,
    NamingValidationError,
    SourceEntry,
    SurnameEntry,
)
from application.naming.resources import load_source_entries, load_surnames
from application.naming.service import (
    build_candidate_pool,
    hydrate_candidate,
    hydrate_candidates,
    validate_name_selections,
)

__all__ = [
    "NameCandidate",
    "NameSelection",
    "NamingValidationError",
    "SourceEntry",
    "SurnameEntry",
    "build_candidate_pool",
    "hydrate_candidate",
    "hydrate_candidates",
    "load_source_entries",
    "load_surnames",
    "validate_name_selections",
]
