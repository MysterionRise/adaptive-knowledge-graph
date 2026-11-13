"""
API payload for a policy's decision record (#306).

``DecisionRecordPayload`` is the envelope a response carries: the fields of a
``DecisionRecord`` (``backend/app/student/policy/base.py``), its ``record_id`` and the time
the decision was taken. The time is not part of the record or of its id: the same decision
taken twice has one ``record_id`` and two ``decided_at`` values. The time carries a UTC
offset; a time without one is refused.
"""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field

from backend.app.student.policy.base import DecisionRecord, Json


class EdgeUsePayload(BaseModel):
    """A graph edge the decision used, with where the edge came from."""

    source: str
    target: str
    relation: str
    provenance: str


class DecisionRecordPayload(BaseModel):
    """What a policy decided and every input it read."""

    record_id: str = Field(
        description="Digest of the fields below except decided_at: equal records share it"
    )
    policy_id: str
    policy_version: str
    action: dict[str, Json] = Field(description="What the policy chose")
    state_used: dict[str, Json] = Field(
        description="The learner state the policy read, with the exact values (not rounded)"
    )
    context_used: dict[str, Json] = Field(description="The context fields the policy read")
    edges_used: list[EdgeUsePayload] = Field(
        default_factory=list, description="The graph edges the policy read"
    )
    decided_at: AwareDatetime = Field(
        description=(
            "When the decision was taken, with a UTC offset (the service stamps UTC); not "
            "part of the record or of record_id"
        )
    )

    @classmethod
    def from_record(cls, record: DecisionRecord, decided_at: datetime) -> "DecisionRecordPayload":
        """Wrap a record for a response.

        Args:
            record: The decision record a policy returned
            decided_at: The time of the decision, supplied by the caller, with a UTC offset

        Raises:
            pydantic.ValidationError: If ``decided_at`` has no UTC offset
        """
        return cls(record_id=record.record_id(), decided_at=decided_at, **record.to_dict())
