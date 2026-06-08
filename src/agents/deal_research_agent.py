from dataclasses import dataclass
from datetime import datetime
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.models import AgentRun, Deal, Fact, ReviewItem
from src.parsers.document_parser import ExtractedFact
from src.services.company_enrichment import CompanyEnrichmentService
from src.services.conflict_service import ConflictService
from src.services.deal_service import DealService, infer_doc_paths_for_deal
from src.services.document_processing import DocumentProcessingService
from src.services.fact_service import FactService
from src.services.metric_service import MetricService
from src.services.source_reliability import SourceReliabilityService
from src.services.web_research import WebResearchService
from src.utils.ids import new_id


@dataclass
class AgentResult:
    run_id: str
    deal_id: str
    company_name: str
    tools_used: list[str]
    accepted_facts: list[dict]
    low_confidence_facts: list[dict]
    stale_metrics: list[dict]
    conflicts: list[dict]
    computed_metrics: list[dict]
    review_items: list[dict]
    citations: list[dict]
    plan: list[dict]
    coverage_gaps: list[dict]
    source_strategy: list[dict]


class DealResearchAgent:
    def __init__(self, db: Session):
        self.db = db
        self.deal_service = DealService(db)
        self.document_service = DocumentProcessingService(db)
        self.fact_service = FactService(db)
        self.conflict_service = ConflictService(db)
        self.metric_service = MetricService(db)
        self.enrichment_service = CompanyEnrichmentService()
        self.web_research_service = WebResearchService()
        self.reliability_service = SourceReliabilityService(db)

    def update_deal_intelligence(
        self,
        deal_id: str | None = None,
        company_name: str | None = None,
        website: str | None = None,
        doc_paths: list[str] | None = None,
    ) -> AgentResult:
        deal = self._resolve_deal(deal_id, company_name, website)
        self.deal_service.clear_generated_intelligence(deal.deal_id)
        run = AgentRun(
            run_id=new_id("run"),
            deal_id=deal.deal_id,
            objective="update_deal_intelligence",
            status="running",
            tools_used="[]",
            trace_json="{}",
        )
        self.db.add(run)
        self.db.flush()

        trace: list[dict] = []
        tools_used: list[str] = []
        plan: list[dict] = []

        tools_used.append("inspect_state")
        state = self._inspect_state(deal, doc_paths)

        # Read the deal's audit log for sources a human previously corrected.
        # The agent uses this to distrust those providers on this run instead
        # of repeating the same mistake -- the source-reliability feedback loop.
        tools_used.append("review_source_reliability")
        reliability = self.reliability_service.context_for_deal(deal.deal_id)
        trace.append(
            {
                "tool": "review_source_reliability",
                "corrected_providers": sorted(reliability.corrected_providers),
                "corrected_source_labels": sorted(reliability.corrected_source_labels),
                "corrections_seen": len(reliability.notes),
            }
        )

        coverage = self._coverage_for_deal(deal)
        source_strategy = self._source_strategy(deal, coverage)
        source_strategy_trace = list(source_strategy)
        trace.append({"tool": "inspect_state", **state})
        plan.extend(self._initial_plan(state, coverage, source_strategy))

        paths = state["doc_paths"]
        processed_facts: list[Fact] = []

        if any(step["action"] == "process_documents" for step in plan):
            for path in paths:
                tools_used.append("extract_document_facts")
                result = self.document_service.process_document(deal, path)
                processed_facts.extend(result["facts"])
                trace.append({"tool": "extract_document_facts", "path": path, "facts": len(result["facts"])})

        if any(step["action"] == "enrich_company" for step in plan):
            tools_used.append("enrich_company")
            enriched = self.enrichment_service.enrich(deal.company.name)
            if enriched:
                deal.company.sector = enriched.sector
                deal.company.geography = enriched.geography
                deal.company.summary = enriched.summary
                for field_name, value in enriched.facts.items():
                    processed_facts.append(
                        self.fact_service.create_fact_from_extraction(
                            company_id=deal.company_id,
                            deal_id=deal.deal_id,
                            extracted=ExtractedFact(
                                field_name=field_name,
                                value_text=value,
                                value_numeric=None,
                                unit=None,
                                currency=None,
                                as_of_date=None,
                                evidence=f"Mock enrichment: {field_name} = {value}",
                                confidence_score=0.82,
                                extraction_method="mock_enrichment",
                            ),
                            source_type="enrichment",
                            source_label="mock_company_provider",
                            provider="mock_company_provider",
                            url=deal.company.website,
                            force_review=SourceReliabilityService.should_force_review(
                                reliability, "mock_company_provider", "mock_company_provider"
                            ),
                            review_reason_override=_unreliable_source_reason(field_name, "mock_company_provider")
                            if SourceReliabilityService.should_force_review(
                                reliability, "mock_company_provider", "mock_company_provider"
                            )
                            else None,
                        )
                    )
            trace.append({"tool": "enrich_company", "enriched": enriched is not None})

        tools_used.append("detect_conflicts")
        conflicts = self.conflict_service.detect_conflicts(deal.deal_id, deal.company_id)
        trace.append({"tool": "detect_conflicts", "conflicts": len(conflicts)})

        coverage = self._coverage_for_deal(deal)
        post_doc_state = self._post_document_findings(deal, conflicts, coverage)
        self._create_missing_materials_review(deal, post_doc_state)
        source_strategy = self._source_strategy(deal, coverage)
        source_strategy_trace = _merge_strategy(source_strategy_trace, source_strategy)
        follow_up_plan = self._follow_up_plan(post_doc_state, coverage, source_strategy)
        plan.extend(follow_up_plan)

        if any(step["action"] == "web_research" for step in follow_up_plan):
            tools_used.append("web_research")
            reason = "; ".join(step["reason"] for step in follow_up_plan if step["action"] == "web_research")
            target_fields = sorted(
                {
                    field
                    for step in source_strategy
                    if step["recommended_tool"] in {"company_site_search", "funding_news_search", "general_web_search"}
                    for field in step["fields"]
                }
            )
            result = self.web_research_service.research_company(deal.company.name, deal.company.website, reason, target_fields)
            web_source_label = "live_web_search" if result.used_live_search else "mock_web_search"
            web_provider = "serper" if result.used_live_search else "mock_web_search"
            web_forced = SourceReliabilityService.should_force_review(reliability, web_provider, web_source_label)
            for extracted in result.facts:
                processed_facts.append(
                    self.fact_service.create_fact_from_extraction(
                        company_id=deal.company_id,
                        deal_id=deal.deal_id,
                        extracted=extracted,
                        source_type="web_search",
                        source_label=web_source_label,
                        provider=web_provider,
                        url=deal.company.website,
                        force_review=web_forced,
                        review_reason_override=_unreliable_source_reason(extracted.field_name, web_provider)
                        if web_forced
                        else None,
                    )
                )
            trace.append(
                {
                    "tool": "web_research",
                    "query": result.query,
                    "facts": len(result.facts),
                    "used_live_search": result.used_live_search,
                    "source_count_by_field": result.source_count_by_field,
                    "clarification_questions": result.clarification_questions,
                }
            )
            self._create_clarification_reviews(deal, result.clarification_questions)
            self._create_missing_required_reviews(deal, self._coverage_for_deal(deal))

        tools_used.append("compute_metrics")
        computed_metrics = self.metric_service.compute_for_deal(deal.deal_id, deal.company_id)
        trace.append({"tool": "compute_metrics", "computed_metrics": len(computed_metrics)})

        tools_used.append("check_staleness")
        self.deal_service.create_staleness_review_items(deal.deal_id, deal.company_id)
        trace.append({"tool": "check_staleness"})

        run.status = "completed"
        run.tools_used = json.dumps(tools_used)
        coverage = self._coverage_for_deal(deal)
        source_strategy = self._source_strategy(deal, coverage)
        source_strategy_trace = _merge_strategy(source_strategy_trace, source_strategy)
        run.trace_json = json.dumps({"trace": trace, "plan": plan, "coverage": coverage, "source_strategy": source_strategy_trace})
        run.completed_at = datetime.utcnow()
        self.db.commit()

        return self._build_result(run.run_id, deal, tools_used, plan, coverage, source_strategy_trace)

    def _resolve_deal(self, deal_id: str | None, company_name: str | None, website: str | None) -> Deal:
        if deal_id:
            deal = self.deal_service.get_deal(deal_id)
            if deal:
                return deal
            raise ValueError(f"Deal not found: {deal_id}")
        if not company_name:
            raise ValueError("Either deal_id or company_name is required")
        return self.deal_service.get_or_create_deal(company_name=company_name, website=website)

    def _inspect_state(self, deal: Deal, doc_paths: list[str] | None) -> dict:
        paths = doc_paths if doc_paths is not None else infer_doc_paths_for_deal(deal)
        return {
            "deal_id": deal.deal_id,
            "company_id": deal.company_id,
            "has_company_profile": bool(deal.company.sector and deal.company.summary),
            "doc_paths": paths,
            "document_count": len(paths),
        }

    def _initial_plan(self, state: dict, coverage: list[dict], source_strategy: list[dict]) -> list[dict]:
        plan: list[dict] = []
        if state["document_count"]:
            plan.append(
                {
                    "action": "process_documents",
                    "reason": f"{state['document_count']} diligence document(s) are available.",
                }
            )
        if not state["has_company_profile"]:
            plan.append(
                {
                    "action": "enrich_company",
                    "reason": "Company profile fields are missing.",
                }
            )
        missing_required = [item["field_name"] for item in coverage if item["status"] == "missing"]
        if missing_required:
            plan.append(
                {
                    "action": "coverage_gap_planning",
                    "reason": f"Missing required fields for this stage: {', '.join(missing_required)}.",
                }
            )
        for strategy in source_strategy:
            plan.append(
                {
                    "action": "choose_source",
                    "reason": f"{strategy['recommended_tool']} for {', '.join(strategy['fields'])}: {strategy['why']}",
                }
            )
        return plan

    def _post_document_findings(self, deal: Deal, conflicts: list, coverage: list[dict]) -> dict:
        metric_status = self.deal_service.current_metric_status(deal.deal_id, deal.company_id)
        stale_metrics = [metric for metric in metric_status if metric["staleness_status"] == "stale"]
        important_missing = sorted(
            item["field_name"]
            for item in coverage
            if item["status"] == "missing" and item["priority"] in {"High", "Medium"}
        )
        return {
            "conflict_count": len(conflicts),
            "stale_metrics": stale_metrics,
            "important_missing": important_missing,
            "document_count": len(infer_doc_paths_for_deal(deal)),
        }

    def _follow_up_plan(self, findings: dict, coverage: list[dict], source_strategy: list[dict]) -> list[dict]:
        reasons = []
        if findings["conflict_count"]:
            reasons.append("conflicting deal facts need external context")
        if findings["stale_metrics"]:
            stale_names = ", ".join(metric["metric_name"] for metric in findings["stale_metrics"])
            reasons.append(f"stale metrics need refresh: {stale_names}")
        if findings["important_missing"]:
            reasons.append(f"important fields are missing: {', '.join(findings['important_missing'])}")
        if findings["document_count"] == 0:
            reasons.append("no diligence materials are available")
        web_fields = [
            field
            for strategy in source_strategy
            if strategy["recommended_tool"] in {"company_site_search", "funding_news_search", "general_web_search"}
            for field in strategy["fields"]
        ]
        if web_fields:
            reasons.append(f"coverage gaps can be researched externally: {', '.join(sorted(set(web_fields)))}")
        if not reasons:
            return []
        return [{"action": "web_research", "reason": "; ".join(reasons)}]

    def _create_missing_materials_review(self, deal: Deal, findings: dict) -> None:
        later_stages = {"Due Diligence", "IC Review", "Term Sheet", "Closed"}
        if findings["document_count"] != 0 or deal.stage not in later_stages:
            return
        exists = (
            self.db.query(ReviewItem)
            .filter(
                ReviewItem.deal_id == deal.deal_id,
                ReviewItem.field_name == "diligence_materials",
                ReviewItem.status == "open",
            )
            .first()
        )
        if exists:
            return
        self.db.add(
            ReviewItem(
                review_id=new_id("review"),
                deal_id=deal.deal_id,
                field_name="diligence_materials",
                reason=f"Deal is in {deal.stage} but has no diligence materials attached.",
                candidate_fact_ids=None,
                priority="High" if deal.stage == "Closed" else "Medium",
            )
        )

    def _create_missing_required_reviews(self, deal: Deal, coverage: list[dict]) -> None:
        for item in coverage:
            if item["status"] != "missing":
                continue
            field_name = item["field_name"]
            exists = (
                self.db.query(ReviewItem)
                .filter(ReviewItem.deal_id == deal.deal_id, ReviewItem.field_name == field_name, ReviewItem.status == "open")
                .first()
            )
            if exists:
                continue
            self.db.add(
                ReviewItem(
                    review_id=new_id("review"),
                    deal_id=deal.deal_id,
                    field_name=field_name,
                    reason=f"{field_name} is required for {deal.stage} but could not be found from the selected source strategy. Recommended next step: {item['next_step']}.",
                    candidate_fact_ids=None,
                    priority=item["priority"],
                )
            )

    def _create_clarification_reviews(self, deal: Deal, questions: list[dict]) -> None:
        for question in questions:
            exists = (
                self.db.query(ReviewItem)
                .filter(ReviewItem.deal_id == deal.deal_id, ReviewItem.field_name == question["field_name"], ReviewItem.status == "open")
                .first()
            )
            if exists:
                continue
            self.db.add(
                ReviewItem(
                    review_id=new_id("review"),
                    deal_id=deal.deal_id,
                    field_name=question["field_name"],
                    reason=question["reason"],
                    candidate_fact_ids=None,
                    priority=question["priority"],
                )
            )

    def _coverage_for_deal(self, deal: Deal) -> list[dict]:
        facts = self.db.query(Fact).filter(Fact.deal_id == deal.deal_id).all()
        accepted_fields = {fact.field_name for fact in facts if fact.review_status == "accepted"}
        any_fields = {fact.field_name for fact in facts}
        metrics = {metric["metric_name"]: metric for metric in self.deal_service.current_metric_status(deal.deal_id, deal.company_id)}
        required = _required_fields_for_stage(deal.stage)
        coverage = []
        for field_name, config in required.items():
            status = "missing"
            if field_name == "company_name" and deal.company.name:
                status = "accepted"
            elif field_name == "website" and deal.company.website:
                status = "accepted"
            elif field_name == "initial_contact" and deal.initial_contact:
                status = "accepted"
            elif field_name == "sector" and (deal.company.sector or "sector" in accepted_fields):
                status = "accepted"
            elif field_name == "geography" and (deal.company.geography or "headquarters" in accepted_fields or "geography" in accepted_fields):
                status = "accepted"
            elif field_name in metrics:
                status = "stale" if metrics[field_name]["staleness_status"] == "stale" else metrics[field_name]["review_status"]
            elif field_name in accepted_fields:
                status = "accepted"
            elif field_name in any_fields:
                status = "review_required"
            coverage.append(
                {
                    "field_name": field_name,
                    "status": status,
                    "priority": config["priority"],
                    "source_preference": config["source_preference"],
                    "next_step": _next_step_for_field(field_name, config["source_preference"], status),
                }
            )
        return coverage

    def _source_strategy(self, deal: Deal, coverage: list[dict]) -> list[dict]:
        missing_or_stale = [item for item in coverage if item["status"] in {"missing", "stale", "review_required"}]
        groups: dict[str, list[str]] = {}
        for item in missing_or_stale:
            source = item["source_preference"]
            if source == "diligence_material":
                tool = "request_diligence_materials" if not infer_doc_paths_for_deal(deal) else "process_documents"
            elif source == "company_or_founder_source":
                tool = "company_site_search"
            elif source == "funding_source":
                tool = "funding_news_search"
            else:
                tool = "general_web_search"
            groups.setdefault(tool, []).append(item["field_name"])

        strategy = []
        for tool, fields in groups.items():
            strategy.append(
                {
                    "recommended_tool": tool,
                    "fields": sorted(fields),
                    "why": _strategy_reason(tool, fields),
                }
            )
        return strategy

    def _build_result(
        self,
        run_id: str,
        deal: Deal,
        tools_used: list[str],
        plan: list[dict],
        coverage: list[dict],
        source_strategy: list[dict],
    ) -> AgentResult:
        facts = self.db.query(Fact).filter(Fact.deal_id == deal.deal_id).all()
        reviews = self.db.query(ReviewItem).filter(ReviewItem.deal_id == deal.deal_id, ReviewItem.status == "open").all()
        conflicts = self.conflict_service.detect_conflicts(deal.deal_id, deal.company_id)
        computed = self.metric_service.compute_for_deal(deal.deal_id, deal.company_id)
        metric_status = self.deal_service.current_metric_status(deal.deal_id, deal.company_id)

        return AgentResult(
            run_id=run_id,
            deal_id=deal.deal_id,
            company_name=deal.company.name,
            tools_used=tools_used,
            accepted_facts=[_fact_dict(fact) for fact in facts if fact.review_status == "accepted"],
            low_confidence_facts=[_fact_dict(fact) for fact in facts if fact.confidence_score < 0.80],
            stale_metrics=[metric for metric in metric_status if metric["staleness_status"] == "stale"],
            conflicts=[
                {
                    "field_name": conflict.field_name,
                    "severity": conflict.severity,
                    "fact_ids": conflict.fact_ids.split(","),
                    "status": conflict.resolution_status,
                }
                for conflict in conflicts
            ],
            computed_metrics=[
                {
                    "metric_name": metric.metric_name,
                    "value": round(metric.value_numeric, 2),
                    "formula": metric.formula,
                    "confidence_score": round(metric.confidence_score, 2),
                    "review_status": metric.review_status,
                    "staleness_status": metric.staleness_status,
                    "quality_flags": json.loads(metric.quality_flags or "[]"),
                }
                for metric in computed
            ],
            review_items=[
                {
                    "review_id": item.review_id,
                    "field_name": item.field_name,
                    "reason": item.reason,
                    "priority": item.priority,
                    "status": item.status,
                    "candidate_fact_ids": item.candidate_fact_ids,
                }
                for item in reviews
            ],
            citations=_citations(self.db, deal.deal_id),
            plan=plan,
            coverage_gaps=coverage,
            source_strategy=source_strategy,
        )


def _unreliable_source_reason(field_name: str, provider: str) -> str:
    return (
        f"{field_name} comes from '{provider}', which an associate previously "
        f"corrected on this deal. Verify against a stronger source before accepting."
    )


def _fact_dict(fact: Fact) -> dict:
    return {
        "fact_id": fact.fact_id,
        "field_name": fact.field_name,
        "value": fact.value_numeric if fact.value_numeric is not None else fact.value_text,
        "currency": fact.currency,
        "unit": fact.unit,
        "as_of_date": fact.as_of_date.isoformat() if fact.as_of_date else None,
        "confidence_score": round(fact.confidence_score, 2),
        "review_status": fact.review_status,
        "staleness_status": fact.staleness_status,
    }


def _required_fields_for_stage(stage: str) -> dict[str, dict]:
    base = {
        "company_name": {"priority": "High", "source_preference": "associate_input"},
        "website": {"priority": "Medium", "source_preference": "company_or_founder_source"},
        "sector": {"priority": "Medium", "source_preference": "company_or_founder_source"},
        "geography": {"priority": "Medium", "source_preference": "company_or_founder_source"},
        "initial_contact": {"priority": "Low", "source_preference": "associate_input"},
    }
    screening = {
        "founders": {"priority": "High", "source_preference": "company_or_founder_source"},
        "market_position": {"priority": "Medium", "source_preference": "company_or_founder_source"},
        "external_investors": {"priority": "Medium", "source_preference": "funding_source"},
        "latest_round": {"priority": "Medium", "source_preference": "funding_source"},
    }
    diligence = {
        "arr": {"priority": "High", "source_preference": "diligence_material"},
        "monthly_burn": {"priority": "High", "source_preference": "diligence_material"},
        "headcount": {"priority": "Medium", "source_preference": "diligence_material"},
        "pre_money_valuation": {"priority": "High", "source_preference": "diligence_material"},
        "runway_months": {"priority": "Medium", "source_preference": "diligence_material"},
    }
    term_sheet = {
        "round": {"priority": "High", "source_preference": "diligence_material"},
        "investment_amount": {"priority": "High", "source_preference": "diligence_material"},
        "lead_investor": {"priority": "High", "source_preference": "diligence_material"},
    }

    fields = dict(base)
    if stage in {"Screening", "Due Diligence", "IC Review", "Term Sheet", "Closed", "Passed"}:
        fields.update(screening)
    if stage in {"Due Diligence", "IC Review", "Term Sheet", "Closed"}:
        fields.update(diligence)
    if stage in {"Term Sheet", "Closed"}:
        fields.update(term_sheet)
    return fields


def _next_step_for_field(field_name: str, source_preference: str, status: str) -> str:
    if status == "stale":
        return f"Refresh {field_name} from newer diligence materials or a recent company-confirmed source."
    if source_preference == "diligence_material":
        return f"Upload or review diligence material containing {field_name}."
    if source_preference == "company_or_founder_source":
        return f"Check company website, founder profile, or public company profile for {field_name}."
    if source_preference == "funding_source":
        return f"Check funding announcements, investor posts, or a Crunchbase-like source for {field_name}."
    return f"Ask the associate to provide {field_name}."


def _strategy_reason(tool: str, fields: list[str]) -> str:
    joined = ", ".join(sorted(fields))
    if tool == "request_diligence_materials":
        return f"{joined} should come from company-provided diligence, but no attached document is available."
    if tool == "process_documents":
        return f"{joined} should be extracted from attached diligence materials before using weaker external sources."
    if tool == "company_site_search":
        return f"{joined} can usually be verified from the company site or founder-controlled profiles."
    if tool == "funding_news_search":
        return f"{joined} should be corroborated across funding announcements, investor posts, and company profiles."
    return f"{joined} requires general public-source research."


def _merge_strategy(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = [dict(item) for item in existing]
    by_tool = {item["recommended_tool"]: item for item in merged}
    for item in incoming:
        current = by_tool.get(item["recommended_tool"])
        if not current:
            copied = dict(item)
            copied["fields"] = list(item["fields"])
            merged.append(copied)
            by_tool[copied["recommended_tool"]] = copied
            continue
        current["fields"] = sorted(set(current["fields"]) | set(item["fields"]))
    return merged


def _citations(db: Session, deal_id: str) -> list[dict]:
    rows = db.execute(
        text(
            """
        SELECT facts.field_name, fact_sources.source_label, fact_sources.quoted_evidence
        FROM facts
        JOIN fact_sources ON facts.fact_id = fact_sources.fact_id
        WHERE facts.deal_id = :deal_id
        ORDER BY facts.field_name
        """
        ),
        {"deal_id": deal_id},
    ).mappings()
    return [dict(row) for row in rows]
