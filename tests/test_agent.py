import unittest
import os
from unittest.mock import patch

from scripts.build_db import build_db
from src.agents.deal_research_agent import DealResearchAgent
from src.database.connection import SessionLocal
from src.agents.reasoning import FixedPlanner, PlannerUnavailable
from src.database.models import AgentRun, Fact
from src.services.review_resolution import ReviewResolutionService


class AgentSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Neutralize every external provider so tests are hermetic and
        # reproducible. With a real SERPER_API_KEY present the agent would
        # otherwise flip to live web search and return non-deterministic
        # extractions (this is why test_rogo failed against a populated .env).
        # We set empty strings rather than pop: the services call
        # load_env_file() which uses os.environ.setdefault, so a popped key is
        # immediately re-read from .env. An empty string is "present but
        # falsy", which both setdefault and the truthy checks respect.
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["SERPER_API_KEY"] = ""
        build_db()

    def test_orbitgrid_flags_conflict_and_low_confidence(self) -> None:
        with SessionLocal() as db:
            result = DealResearchAgent(db).update_deal_intelligence(deal_id="d_orbit")

        self.assertTrue(any(item["field_name"] == "pre_money_valuation" for item in result.conflicts))
        self.assertTrue(any(fact["field_name"] == "headcount" for fact in result.low_confidence_facts))
        self.assertTrue(any(metric["metric_name"] == "arr_valuation_multiple" for metric in result.computed_metrics))
        self.assertTrue(any(step["action"] == "web_research" for step in result.plan))
        self.assertTrue(result.citations)

    def test_novaledger_flags_stale_metrics(self) -> None:
        with SessionLocal() as db:
            result = DealResearchAgent(db).update_deal_intelligence(deal_id="d_nova")

        self.assertTrue(any(metric["metric_name"] == "arr" for metric in result.stale_metrics))
        self.assertTrue(any(item["field_name"] == "arr" for item in result.review_items))
        self.assertTrue(all(metric["review_status"] == "review_required" for metric in result.computed_metrics))
        self.assertTrue(all(metric["staleness_status"] == "stale" for metric in result.computed_metrics))
        self.assertTrue(any(step["action"] == "web_research" for step in result.plan))

    def test_rogo_starts_from_web_research_without_documents(self) -> None:
        with SessionLocal() as db:
            result = DealResearchAgent(db).update_deal_intelligence(deal_id="d_rogo")

        self.assertTrue(any(step["action"] == "web_research" for step in result.plan))
        self.assertTrue(any(step["action"] == "coverage_gap_planning" for step in result.plan))
        self.assertTrue(any(item["recommended_tool"] == "company_site_search" for item in result.source_strategy))
        self.assertTrue(any(fact["field_name"] == "founders" for fact in result.accepted_facts))
        self.assertFalse(any(item["field_name"] == "founders" for item in result.review_items))


class HumanCorrectionDurabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["SERPER_API_KEY"] = ""
        build_db()

    def test_human_corrections_survive_a_re_run(self) -> None:
        # First run surfaces a low-confidence headcount for human review.
        with SessionLocal() as db:
            first = DealResearchAgent(db).update_deal_intelligence(deal_id="d_orbit")
        review = next(item for item in first.review_items if item["field_name"] == "headcount")

        # The associate corrects the value by hand.
        with SessionLocal() as db:
            ReviewResolutionService(db).resolve_review_item(review["review_id"], "37 employees", None)

        # A subsequent agent run must NOT erase the human-entered fact.
        with SessionLocal() as db:
            DealResearchAgent(db).update_deal_intelligence(deal_id="d_orbit")
            human_facts = (
                db.query(Fact)
                .filter(Fact.deal_id == "d_orbit", Fact.extraction_method == "associate_correction")
                .all()
            )

        self.assertTrue(human_facts, "human correction was wiped by the next agent run")
        self.assertTrue(all(fact.review_status == "accepted" for fact in human_facts))
        self.assertTrue(all(fact.locked for fact in human_facts))


class SourceReliabilityFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["SERPER_API_KEY"] = ""
        build_db()

    def test_corrected_provider_is_distrusted_for_other_fields(self) -> None:
        # First run: Rogo is researched via the mocked web provider, which
        # confidently returns `founders` (auto-accepted) among other fields.
        with SessionLocal() as db:
            first = DealResearchAgent(db).update_deal_intelligence(deal_id="d_rogo")
        self.assertTrue(any(fact["field_name"] == "founders" for fact in first.accepted_facts))
        market = next(item for item in first.review_items if item["field_name"] == "market_position")

        # The associate corrects a DIFFERENT field from that same provider,
        # which records the provider as having been wrong.
        with SessionLocal() as db:
            ReviewResolutionService(db).resolve_review_item(market["review_id"], "Corrected positioning", None)

        # Next run: the agent should now distrust that provider and route its
        # other facts (e.g. founders) to review instead of auto-accepting.
        with SessionLocal() as db:
            DealResearchAgent(db).update_deal_intelligence(deal_id="d_rogo")
            founders = (
                db.query(Fact)
                .filter(Fact.deal_id == "d_rogo", Fact.field_name == "founders")
                .order_by(Fact.created_at.desc())
                .first()
            )

        self.assertIsNotNone(founders)
        self.assertEqual(founders.review_status, "review_required")


class RunAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["SERPER_API_KEY"] = ""
        build_db()

    def test_failed_run_preserves_state_and_records_failure(self) -> None:
        # Establish committed state, including a locked human fact.
        with SessionLocal() as db:
            first = DealResearchAgent(db).update_deal_intelligence(deal_id="d_orbit")
        review = next(item for item in first.review_items if item["field_name"] == "headcount")
        with SessionLocal() as db:
            ReviewResolutionService(db).resolve_review_item(review["review_id"], "37 employees", None)

        with SessionLocal() as db:
            facts_before = db.query(Fact).filter(Fact.deal_id == "d_orbit").count()

        # A run that blows up midway (after the wipe + re-extraction) must not
        # leave the deal in a half-rebuilt state.
        with SessionLocal() as db:
            agent = DealResearchAgent(db)
            with patch.object(agent.metric_service, "compute_for_deal", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    agent.update_deal_intelligence(deal_id="d_orbit")

        with SessionLocal() as db:
            facts_after = db.query(Fact).filter(Fact.deal_id == "d_orbit").count()
            human = (
                db.query(Fact)
                .filter(Fact.deal_id == "d_orbit", Fact.extraction_method == "associate_correction")
                .count()
            )
            failed_runs = (
                db.query(AgentRun)
                .filter(AgentRun.deal_id == "d_orbit", AgentRun.status == "failed")
                .count()
            )

        self.assertEqual(facts_after, facts_before, "a failed run corrupted the fact set")
        self.assertEqual(human, 1, "the locked human correction was lost")
        self.assertEqual(failed_runs, 1, "the failed run was not recorded in the audit trail")


class ReasoningLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["SERPER_API_KEY"] = ""
        build_db()

    def test_loop_executes_planner_chosen_tools_in_order(self) -> None:
        # A scripted planner stands in for the LLM so the loop can be tested
        # without a model. The loop must run the chosen tools, in order, and
        # produce the same kind of cited results as the deterministic path.
        actions = [
            "process_documents",
            "enrich_company",
            "detect_conflicts",
            "compute_metrics",
            "check_staleness",
            "finish",
        ]
        with SessionLocal() as db:
            agent = DealResearchAgent(db, planner=FixedPlanner(actions))
            result = agent.update_deal_intelligence(deal_id="d_orbit")

        planned_actions = [step["action"] for step in result.plan]
        self.assertEqual(planned_actions[: len(actions)], actions)
        self.assertTrue(any(metric["metric_name"] == "arr_valuation_multiple" for metric in result.computed_metrics))
        self.assertTrue(result.accepted_facts)

    def test_loop_can_stop_immediately(self) -> None:
        with SessionLocal() as db:
            agent = DealResearchAgent(db, planner=FixedPlanner(["finish"]))
            result = agent.update_deal_intelligence(deal_id="d_orbit")
        self.assertEqual([step["action"] for step in result.plan], ["finish"])
        self.assertEqual(result.computed_metrics, [])

    def test_loop_stops_repeating_a_tool_that_makes_no_progress(self) -> None:
        # A planner that fixates on one tool must not spin to the step cap.
        # The loop should detect that a repeated tool closes no new coverage
        # gap and stop offering it.
        with SessionLocal() as db:
            agent = DealResearchAgent(db, planner=FixedPlanner(["web_research"] * 8))
            result = agent.update_deal_intelligence(deal_id="d_rogo")
        self.assertLessEqual(result.tools_used.count("web_research"), 2)

    def test_falls_back_to_deterministic_when_planner_unavailable(self) -> None:
        # If the LLM planner cannot be reached, the run must still produce a
        # full, cited report via the deterministic plan -- not an empty one.
        class _AlwaysUnavailablePlanner:
            def decide(self, context):
                raise PlannerUnavailable("simulated model outage")

        with SessionLocal() as db:
            agent = DealResearchAgent(db, planner=_AlwaysUnavailablePlanner())
            result = agent.update_deal_intelligence(deal_id="d_orbit")

        self.assertTrue(any(conflict["field_name"] == "pre_money_valuation" for conflict in result.conflicts))
        self.assertTrue(any(metric["metric_name"] == "arr_valuation_multiple" for metric in result.computed_metrics))


if __name__ == "__main__":
    unittest.main()
