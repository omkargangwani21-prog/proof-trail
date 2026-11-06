from typing import Literal
from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    record_id: str
    field: str
    quoted_value: str


class Claim(BaseModel):
    claim_id: str
    text: str
    type: Literal["fulfillment", "authorization", "policy", "history", "other"]
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)


class Draft(BaseModel):
    decision: Literal["CONTEST", "ACCEPT", "ABSTAIN"]
    rationale: str
    claims: list[Claim]
    missing_evidence: list[str]
