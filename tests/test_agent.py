import unittest
import os

from scripts.build_db import build_db
from src.agents.deal_research_agent import DealResearchAgent
from src.database.connection import SessionLocal


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


if __name__ == "__main__":
    unittest.main()
