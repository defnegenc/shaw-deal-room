import unittest

from src.services.web_research import _dedupe_web_facts, _targeted_queries, _website_from_snippets
from src.parsers.document_parser import ExtractedFact


class WebsiteFromSnippetsTests(unittest.TestCase):
    def test_picks_company_domain_over_social_and_news(self):
        snippets = [
            {"title": "Cognition | LinkedIn", "snippet": "...", "link": "https://www.linkedin.com/company/cognition"},
            {"title": "Cognition raises funding", "snippet": "...", "link": "https://techcrunch.com/2024/cognition"},
            {"title": "Cognition", "snippet": "Devin, the AI engineer", "link": "https://cognition.ai/"},
        ]
        fact = _website_from_snippets(snippets, "Cognition")
        self.assertIsNotNone(fact)
        self.assertEqual(fact.field_name, "website")
        self.assertEqual(fact.value_text, "https://cognition.ai")

    def test_returns_none_when_no_company_domain(self):
        snippets = [{"title": "x", "snippet": "y", "link": "https://techcrunch.com/article"}]
        self.assertIsNone(_website_from_snippets(snippets, "Cognition"))


class TargetedQueriesTests(unittest.TestCase):
    def test_adds_founder_and_website_searches_when_missing(self):
        queries = _targeted_queries("Cognition", ["founders", "website"], set())
        self.assertTrue(any("founders" in q for q in queries))
        self.assertTrue(any("official website" in q for q in queries))

    def test_skips_fields_already_found(self):
        queries = _targeted_queries("Cognition", ["founders", "website"], {"founders", "website"})
        self.assertEqual(queries, [])


class DedupeWebFactsTests(unittest.TestCase):
    def test_keeps_highest_confidence_per_field(self):
        def fact(name, conf):
            return ExtractedFact(name, "v", None, None, None, None, "e", conf, "serper_web_search")

        deduped = _dedupe_web_facts([fact("founders", 0.6), fact("founders", 0.92), fact("sector", 0.8)])
        by_field = {f.field_name: f.confidence_score for f in deduped}
        self.assertEqual(by_field, {"founders": 0.92, "sector": 0.8})


if __name__ == "__main__":
    unittest.main()
