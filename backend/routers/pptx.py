import os
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

import pptx_builder
import rag
import prototypes
from schemas import GeneratePptxRequest

router = APIRouter()


@router.post("/api/generate_pptx")
async def generate_pptx(req: GeneratePptxRequest):
    data = req.data.model_copy(deep=True)
    if not req.generate_illustrations:
        for case in data.cases:
            if case.image_source in {"generated", "library"} or (case.image_source is None and case.image_reusable):
                case.image_b64 = None
                case.image_reusable = False

    if not os.path.exists(pptx_builder.TEMPLATE_PATH):
        raise HTTPException(status_code=500, detail="Template not found")

    try:
        output_io = await run_in_threadpool(
            pptx_builder.build_pptx, data, audit_type=req.audit_type or "full", auditor=req.auditor
        )
    except prototypes.PrototypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if req.save_to_memory:
        try:
            rag.save_report_to_memory(data)
        except Exception as e:
            print(f"Failed to save to RAG memory: {e}")

    return StreamingResponse(
        output_io,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": (
                "attachment; filename=report.pptx; "
                f"filename*=UTF-8''{quote('Отчет_' + data.client_name.replace(' ', '_') + '.pptx')}"
            )
        }
    )
