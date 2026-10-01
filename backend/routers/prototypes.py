from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

import prototypes

router = APIRouter()


@router.post("/api/prototypes")
async def upload_prototypes(files: list[UploadFile] = File(...)):
    created = []
    try:
        if not 1 <= len(files) <= prototypes.MAX_FILES:
            raise prototypes.PrototypeError("Можно загрузить от 1 до 5 файлов")
        total = 0
        for file in files:
            raw = await file.read(prototypes.MAX_FILE_BYTES + 1)
            total += len(raw)
            if total > prototypes.MAX_TOTAL_BYTES:
                raise prototypes.PrototypeError("Общий размер файлов не должен превышать 45 МБ")
            document = await run_in_threadpool(prototypes.ingest, file.filename or "prototype.docx", raw)
            created.append(document)
        return {"documents": [prototypes.summary(d) for d in created]}
    except prototypes.PrototypeError as exc:
        for document in created:
            prototypes.discard(document["id"])
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        for file in files:
            await file.close()


@router.get("/api/prototypes/{source_id}")
async def get_prototype(source_id: str):
    try:
        return prototypes.summary(await run_in_threadpool(prototypes.load, source_id))
    except prototypes.PrototypeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
