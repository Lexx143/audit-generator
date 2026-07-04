import os
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import pptx_builder
import rag
from schemas import GeneratePptxRequest

router = APIRouter()


@router.post("/api/generate_pptx")
async def generate_pptx(req: GeneratePptxRequest):
    data = req.data

    if not os.path.exists(pptx_builder.TEMPLATE_PATH):
        raise HTTPException(status_code=500, detail="Template not found")

    output_io = pptx_builder.build_pptx(
        data, audit_type=req.audit_type or "full", auditor=req.auditor
    )

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
