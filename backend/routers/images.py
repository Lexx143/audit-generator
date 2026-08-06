from fastapi import APIRouter, HTTPException

import imaging
import llm
import rag
from schemas import Auditor, GenerateImageRequest, ImageSuggestionsRequest

router = APIRouter()


@router.post("/api/generate_image")
async def generate_image(req: GenerateImageRequest):
    try:
        scene = req.prompt
        # если пришла суть кейса — строим подробную сцену через LLM
        if req.vulnerability:
            try:
                scene = await llm.build_image_prompt(
                    req.title or "", req.vulnerability, req.risk or "")
            except Exception as e:
                print(f"build_image_prompt failed, fallback to short prompt: {e}")
                scene = req.prompt
        image_b64 = await imaging.generate_image_b64(scene, req.style or "3d_icon")
        return {"image_b64": image_b64, "prompt": scene}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/image_suggestions")
async def image_suggestions(req: ImageSuggestionsRequest):
    try:
        images = rag.find_similar_images(req.title, req.vulnerability or "", n=req.n)
        return {"images": images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/auditors")
async def list_auditors():
    return {"auditors": rag.get_auditors()}


@router.post("/api/auditors")
async def create_auditor(req: Auditor):
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="Имя не может быть пустым")
    photo = req.photo_b64
    if photo:
        try:
            photo = imaging.prepare_auditor_photo(photo)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Не удалось обработать фото: {e}")
    return rag.save_auditor(req.name, photo)
