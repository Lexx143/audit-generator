import json

from fastapi import APIRouter, HTTPException

import llm
import rag
from schemas import ParseRequest, ReviseRequest, ReviseCaseRequest

router = APIRouter()


@router.get("/api/hints")
async def get_hints_api():
    return {"hints": rag.get_hints()}


@router.get("/api/categories")
async def get_categories_api():
    return {"categories": rag.get_categories()}


@router.post("/api/categories")
async def add_category_api(payload: dict):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название категории пустое")
    return {"categories": rag.add_category(name)}


@router.post("/api/parse")
async def parse_audit(req: ParseRequest):
    try:
        data_obj = await llm.generate_structure(req)
        return json.loads(data_obj.model_dump_json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/revise")
async def revise_audit(req: ReviseRequest):
    try:
        data_obj = await llm.revise_structure(req)
        return json.loads(data_obj.model_dump_json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/revise_case")
async def revise_case(req: ReviseCaseRequest):
    try:
        case_obj = await llm.revise_single_case(req)
        return json.loads(case_obj.model_dump_json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
