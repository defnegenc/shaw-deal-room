from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    website: Mapped[str | None] = mapped_column(String)
    sector: Mapped[str | None] = mapped_column(String)
    geography: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deals: Mapped[list["Deal"]] = relationship(back_populates="company")


class Deal(Base):
    __tablename__ = "deals"

    deal_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String, default="Medium")
    status: Mapped[str] = mapped_column(String, default="Active")
    initial_contact: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company: Mapped[Company] = relationship(back_populates="deals")
    documents: Mapped[list["Document"]] = relationship(back_populates="deal")


class DealEvent(Base):
    __tablename__ = "deal_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    deal_id: Mapped[str] = mapped_column(String, nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String, default="field_change")
    fact_id: Mapped[str | None] = mapped_column(String)
    source_id: Mapped[str | None] = mapped_column(String)
    source_label: Mapped[str | None] = mapped_column(String)
    provider: Mapped[str | None] = mapped_column(String)
    changed_by: Mapped[str] = mapped_column(String, default="Associate")
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[str] = mapped_column(String, default="unknown")
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    processing_status: Mapped[str] = mapped_column(String, default="pending")

    deal: Mapped[Deal] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.document_id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_label: Mapped[str] = mapped_column(String, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Fact(Base):
    __tablename__ = "facts"

    fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), nullable=False)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_numeric: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str | None] = mapped_column(String)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    extraction_method: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String, default="proposed")
    staleness_status: Mapped[str] = mapped_column(String, default="current")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FactSource(Base):
    __tablename__ = "fact_sources"

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("facts.fact_id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.document_id"))
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("document_chunks.chunk_id"))
    source_label: Mapped[str | None] = mapped_column(String)
    quoted_evidence: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)


class MetricObservation(Base):
    __tablename__ = "metric_observations"

    metric_observation_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), nullable=False)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str | None] = mapped_column(String)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("fact_sources.source_id"))
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String, default="proposed")
    staleness_status: Mapped[str] = mapped_column(String, default="current")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ComputedMetric(Base):
    __tablename__ = "computed_metrics"

    metric_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), nullable=False)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    value_numeric: Mapped[float] = mapped_column(Float, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    input_fact_ids: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String, default="accepted")
    staleness_status: Mapped[str] = mapped_column(String, default="current")
    quality_flags: Mapped[str] = mapped_column(Text, default="[]")


class Conflict(Base):
    __tablename__ = "conflicts"

    conflict_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), nullable=False)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    fact_ids: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    resolution_status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReviewItem(Base):
    __tablename__ = "review_items"

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_fact_ids: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String, default="Medium")
    status: Mapped[str] = mapped_column(String, default="open")
    resolution_outcome: Mapped[str | None] = mapped_column(String)
    resolved_fact_id: Mapped[str | None] = mapped_column(String)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.deal_id"), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    tools_used: Mapped[str] = mapped_column(Text, default="[]")
    trace_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
