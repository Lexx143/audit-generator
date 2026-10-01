from pydantic import BaseModel, Field
from typing import Literal, Optional


class Case(BaseModel):
    title: str
    vulnerability: str
    risk: str
    recommendation: Optional[str]
    priority: str
    category: str
    image_prompt: str
    image_b64: Optional[str] = None
    # Можно ли сохранить картинку в библиотеку для будущих аудитов
    # (сгенерированные и загруженные иллюстрации — да, фотографии объектов — нет)
    image_reusable: Optional[bool] = None
    image_source: Optional[Literal["generated", "library", "uploaded"]] = None


class AuditStructure(BaseModel):
    client_name: str
    review: str
    cases: list[Case]
    conclusions: list[str]


class AuditData(AuditStructure):
    # Ссылки на оригиналы хранит приложение, а не генерирует модель.
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class ParseRequest(BaseModel):
    general_data: str
    vulnerabilities: str
    conclusions: str
    audit_type: str
    source_ids: list[str] = Field(default_factory=list, max_length=5)
    generate_illustrations: bool = True


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
    # если переданы — бэкенд строит подробный промпт из сути кейса
    title: Optional[str] = None
    vulnerability: Optional[str] = None
    risk: Optional[str] = None
    generate_illustrations: bool = True


class Auditor(BaseModel):
    id: Optional[str] = None
    name: str
    photo_b64: Optional[str] = None


class GeneratePptxRequest(BaseModel):
    data: AuditData
    audit_type: Optional[str] = "full"
    save_to_memory: bool = False
    auditor: Optional[Auditor] = None
    generate_illustrations: bool = True


class ImageSuggestionsRequest(BaseModel):
    title: str
    vulnerability: Optional[str] = ""
    n: int = 6
