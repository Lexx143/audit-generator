from fastapi import APIRouter, HTTPException

import imaging
from schemas import GenerateImageRequest

router = APIRouter()


@router.post("/api/generate_image")
async def generate_image(req: GenerateImageRequest):
    try:
        image_b64 = await imaging.generate_image_b64(req.prompt, req.style or "3d_icon")
        return {"image_b64": image_b64}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
