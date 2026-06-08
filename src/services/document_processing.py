from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from src.database.models import Deal, Document, DocumentChunk
from src.parsers.document_parser import MONEY_FIELDS, NUMBER_FIELDS, TEXT_FIELDS, chunk_text, extract_facts, parse_document_type, read_text
from src.services.fact_service import FactService
from src.services.llm_extraction import LLMExtractionService
from src.utils.ids import new_id


class DocumentProcessingService:
    def __init__(self, db: Session):
        self.db = db
        self.fact_service = FactService(db)
        self.llm_extraction = LLMExtractionService()

    def process_document(self, deal: Deal, path: str) -> dict:
        suffix = Path(path).suffix.lower()
        text = read_text(path)
        document = Document(
            document_id=new_id("doc"),
            deal_id=deal.deal_id,
            filename=Path(path).name,
            doc_type=parse_document_type(text),
            storage_path=str(path),
            processing_status="processing",
        )
        self.db.add(document)
        self.db.flush()

        chunks = []
        for index, chunk in enumerate(chunk_text(text)):
            db_chunk = DocumentChunk(
                chunk_id=new_id("chunk"),
                document_id=document.document_id,
                chunk_index=index,
                text=chunk,
                source_label=f"{document.filename} chunk {index + 1}",
            )
            self.db.add(db_chunk)
            chunks.append(db_chunk)
        self.db.flush()

        facts = []
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".heic"}:
            try:
                extracted_facts = self.llm_extraction.extract_image_facts(path, _supported_fields())
            except RuntimeError:
                extracted_facts = []
        else:
            extracted_facts = extract_facts(text)
            try:
                extracted_facts.extend(self.llm_extraction.extract_missing_facts(text, _missing_fields(extracted_facts)))
            except RuntimeError:
                # The deterministic path remains usable if the optional LLM provider
                # is unavailable, misconfigured, or blocked by local network policy.
                pass

        for extracted in extracted_facts:
            chunk = _best_chunk_for_evidence(chunks, extracted.evidence)
            facts.append(
                self.fact_service.create_fact_from_extraction(
                    company_id=deal.company_id,
                    deal_id=deal.deal_id,
                    extracted=extracted,
                    source_type="document",
                    source_label=chunk.source_label if chunk else document.filename,
                    document_id=document.document_id,
                    chunk_id=chunk.chunk_id if chunk else None,
                )
            )

        document.processed_at = datetime.utcnow()
        document.processing_status = "processed"
        return {"document": document, "facts": facts}


def _best_chunk_for_evidence(chunks: list[DocumentChunk], evidence: str) -> DocumentChunk | None:
    for chunk in chunks:
        if evidence in chunk.text:
            return chunk
    return chunks[0] if chunks else None


def _missing_fields(extracted_facts: list) -> set[str]:
    supported = _supported_fields()
    present = {fact.field_name for fact in extracted_facts}
    return supported - present


def _supported_fields() -> set[str]:
    return set(MONEY_FIELDS) | set(NUMBER_FIELDS) | set(TEXT_FIELDS)
