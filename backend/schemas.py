from pydantic import BaseModel
from typing import Optional


class Case(BaseModel):
    title: str
    vulnerability: str
    risk: str
    recommendation: Optional[str]
    priority: str
    category: str
    image_prompt: str
    image_b64: Optional[str] = None


class AuditData(BaseModel):
    client_name: str
    review: str
    cases: list[Case]
    conclusions: list[str]


class ParseRequest(BaseModel):
    general_data: str
    vulnerabilities: str
    conclusions: str
    audit_type: str


class ReviseRequest(BaseModel):
    current_data: AuditData
    revision_prompt: str
    audit_type: str


class ReviseCaseRequest(BaseModel):
    case: Case
    comment: str
    audit_type: str
    general_data: Optional[str] = ""


class GenerateImageRequest(BaseModel):
    prompt: str
    style: Optional[str] = "3d_icon"


class GeneratePptxRequest(BaseModel):
    data: AuditData
    audit_type: Optional[str] = "full"
    save_to_memory: bool = False
