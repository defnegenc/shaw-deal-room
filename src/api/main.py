from dataclasses import asdict
from pathlib import Path
import re

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.agents.deal_research_agent import DealResearchAgent
from src.database.connection import get_db, init_db
from src.database.models import Company, Deal, DealEvent
from src.parsers.document_parser import normalize_document_type
from src.services.deal_service import DealService, infer_doc_paths_for_deal, log_deal_event
from src.services.review_resolution import ReviewResolutionService
from src.services.seed_data import seed_if_empty

app = FastAPI(title="AI Deal Room MVP", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AgentRunRequest(BaseModel):
    deal_id: str | None = None
    company_name: str | None = Field(default=None, examples=["OrbitGrid AI"])
    website: str | None = None
    doc_paths: list[str] | None = Field(default=None, examples=[["data/documents/orbit_pitch_q1_2026.txt"]])


class CreateDealRequest(BaseModel):
    company_name: str = Field(examples=["Rogo"])
    website: str | None = Field(default=None, examples=["https://rogo.ai"])
    stage: str = Field(default="Sourced", examples=["Sourced"])
    status: str = Field(default="Active", examples=["Active"])
    initial_contact: str | None = Field(default=None, examples=["hello@rogo.ai"])


class UpdateDealRequest(BaseModel):
    company_name: str | None = None
    website: str | None = None
    stage: str | None = None
    status: str | None = None
    initial_contact: str | None = None


class ResolveReviewRequest(BaseModel):
    raw_value: str = Field(examples=["$12,000,000 as of Q1 2026"])
    as_of_text: str | None = Field(default=None, examples=["Q1 2026"])


@app.on_event("startup")
def startup() -> None:
    init_db()
    for db in get_db():
        seed_if_empty(db)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ui")
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/ui/deals/{deal_id}")
def deal_room_ui(deal_id: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/deals")
def list_deals(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Deal, Company).join(Company, Deal.company_id == Company.company_id).order_by(Company.name).all()
    return [
        {
            "deal_id": deal.deal_id,
            "company_name": company.name,
            "website": company.website,
            "stage": deal.stage,
            "status": deal.status,
            "initial_contact": deal.initial_contact,
        }
        for deal, company in rows
    ]


@app.post("/deals")
def create_deal(payload: CreateDealRequest, db: Session = Depends(get_db)) -> dict:
    deal = DealService(db).get_or_create_deal(
        company_name=payload.company_name,
        website=payload.website,
        owner="Associate",
    )
    deal.stage = payload.stage
    deal.status = payload.status
    deal.initial_contact = payload.initial_contact
    log_deal_event(db, deal.deal_id, "deal_created", None, payload.company_name)
    db.commit()
    db.refresh(deal)
    return {
        "deal_id": deal.deal_id,
        "company_name": deal.company.name,
        "website": deal.company.website,
        "stage": deal.stage,
        "status": deal.status,
        "initial_contact": deal.initial_contact,
    }


@app.patch("/deals/{deal_id}")
def update_deal(deal_id: str, payload: UpdateDealRequest, db: Session = Depends(get_db)) -> dict:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    updates = payload.model_dump(exclude_unset=True)
    if "company_name" in updates and updates["company_name"] is not None:
        log_deal_event(db, deal_id, "company_name", deal.company.name, updates["company_name"])
        deal.company.name = updates["company_name"]
    if "website" in updates:
        log_deal_event(db, deal_id, "website", deal.company.website, updates["website"])
        deal.company.website = updates["website"]
    for field in ["stage", "status", "initial_contact"]:
        if field in updates:
            log_deal_event(db, deal_id, field, getattr(deal, field), updates[field])
            setattr(deal, field, updates[field])

    db.commit()
    db.refresh(deal)
    return _deal_payload(deal)


@app.delete("/deals/{deal_id}")
def delete_deal(deal_id: str, db: Session = Depends(get_db)) -> dict:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    company = deal.company
    DealService(db).clear_generated_intelligence(deal_id)
    db.delete(deal)
    db.flush()
    if not db.query(Deal).filter(Deal.company_id == company.company_id).first():
        db.delete(company)
    db.commit()
    return {"deleted": True, "deal_id": deal_id}


@app.get("/deals/{deal_id}/events")
def deal_events(deal_id: str, db: Session = Depends(get_db)) -> list[dict]:
    events = db.query(DealEvent).filter(DealEvent.deal_id == deal_id).order_by(DealEvent.changed_at.desc()).all()
    return [
        {
            "event_id": event.event_id,
            "field_name": event.field_name,
            "old_value": event.old_value,
            "new_value": event.new_value,
            "changed_by": event.changed_by,
            "reason": event.reason,
            "changed_at": event.changed_at.isoformat(),
        }
        for event in events
    ]


@app.get("/deals/{deal_id}/source-documents")
def source_documents(deal_id: str, db: Session = Depends(get_db)) -> list[dict]:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return [
        {
            "filename": Path(path).name,
            "path": path,
            "doc_type": normalize_document_type(Path(path).suffix.lower().lstrip(".") or "unknown"),
            "view_url": f"/deals/{deal_id}/source-documents/view?filename={Path(path).name}",
            "download_url": f"/deals/{deal_id}/source-documents/download?filename={Path(path).name}",
        }
        for path in infer_doc_paths_for_deal(deal)
    ]


@app.post("/deals/{deal_id}/source-documents")
async def upload_source_document(
    deal_id: str,
    file: UploadFile = File(...),
    doc_type: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    filename = Path(file.filename or "uploaded_document").name
    if Path(filename).suffix.lower() not in {".txt", ".md", ".pdf", ".xlsx", ".xlsm", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".heic"}:
        raise HTTPException(status_code=400, detail="Supported files: .txt, .md, .pdf, .xlsx, .xlsm, .csv, .png, .jpg, .jpeg, .webp, .heic")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
    path = Path("data/documents") / f"{deal_id}_{safe_name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(await file.read())
    normalized_doc_type = normalize_document_type(doc_type or Path(filename).suffix.lower().lstrip(".") or "unknown")
    log_deal_event(db, deal_id, "document_upload", None, f"{path.name} ({normalized_doc_type})")
    db.commit()
    return {
        "filename": path.name,
        "path": str(path),
        "doc_type": normalized_doc_type,
        "view_url": f"/deals/{deal_id}/source-documents/view?filename={path.name}",
        "download_url": f"/deals/{deal_id}/source-documents/download?filename={path.name}",
    }


@app.get("/deals/{deal_id}/source-documents/view")
def view_source_document(deal_id: str, filename: str = Query(...), db: Session = Depends(get_db)) -> FileResponse:
    path = _safe_source_document_path(deal_id, filename, db)
    return FileResponse(path, media_type="text/plain")


@app.get("/deals/{deal_id}/source-documents/download")
def download_source_document(deal_id: str, filename: str = Query(...), db: Session = Depends(get_db)) -> FileResponse:
    path = _safe_source_document_path(deal_id, filename, db)
    return FileResponse(path, media_type="text/plain", filename=path.name)


@app.post("/agent-runs/update-deal-intelligence")
def update_deal_intelligence(payload: AgentRunRequest, db: Session = Depends(get_db)) -> dict:
    result = DealResearchAgent(db).update_deal_intelligence(
        deal_id=payload.deal_id,
        company_name=payload.company_name,
        website=payload.website,
        doc_paths=payload.doc_paths,
    )
    return asdict(result)


@app.post("/review-items/{review_id}/resolve")
def resolve_review_item(review_id: str, payload: ResolveReviewRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return ReviewResolutionService(db).resolve_review_item(
            review_id=review_id,
            raw_value=payload.raw_value,
            as_of_text=payload.as_of_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _safe_source_document_path(deal_id: str, filename: str, db: Session) -> Path:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    allowed = {Path(path).name: Path(path).resolve() for path in infer_doc_paths_for_deal(deal)}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Document not found for this deal")
    return allowed[filename]


def _deal_payload(deal: Deal) -> dict:
    return {
        "deal_id": deal.deal_id,
        "company_name": deal.company.name,
        "website": deal.company.website,
        "stage": deal.stage,
        "status": deal.status,
        "initial_contact": deal.initial_contact,
    }
