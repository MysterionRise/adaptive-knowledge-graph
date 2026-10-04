"""
Constrained field types shared by request payloads and route parameters.

This module only depends on pydantic, so payload models (``backend.app.ui_payloads``)
and the API routes can both import it without creating import cycles. Route code
should import these names from ``backend.app.api.validators``.

Strings are stripped before their length is checked, so whitespace-only input fails
``min_length``.
"""

from typing import Annotated

from pydantic import StringConstraints

SUBJECT_ID_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
"""Subject IDs are lowercase slugs such as ``us_history``."""

STUDENT_ID_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"
"""Student IDs: 1-64 letters, digits, ``_``, ``.`` or ``-``."""

DEFAULT_STUDENT_ID = "default"

NonBlankStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
"""Free text: stripped, 1-2000 characters."""

QuestionStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]
"""A learner's question: stripped, 3-2000 characters."""

TopicStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
"""A quiz topic: stripped, 1-500 characters."""

SearchQueryStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
"""A search query: stripped, 1-500 characters."""

ConceptStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
"""A concept name: stripped, 1-200 characters."""

SubjectId = Annotated[str, StringConstraints(pattern=SUBJECT_ID_PATTERN)]
StudentId = Annotated[str, StringConstraints(pattern=STUDENT_ID_PATTERN)]
