import unittest

from src.parsers.document_parser import extract_facts


class MoneyScalingTests(unittest.TestCase):
    def test_parses_millions(self):
        facts = {f.field_name: f for f in extract_facts("ARR: $12.4M")}
        self.assertIn("arr", facts)
        self.assertEqual(facts["arr"].value_numeric, 12_400_000)

    def test_parses_thousands(self):
        facts = {f.field_name: f for f in extract_facts("Monthly burn: $850K")}
        self.assertIn("monthly_burn", facts)
        self.assertEqual(facts["monthly_burn"].value_numeric, 850_000)

    def test_parses_billions(self):
        # A late-stage valuation can be stated in billions; the document lane
        # must scale "B" the same way it scales "M" and "K".
        facts = {f.field_name: f for f in extract_facts("Post-money valuation: $1.2B")}
        self.assertIn("post_money_valuation", facts)
        self.assertEqual(facts["post_money_valuation"].value_numeric, 1_200_000_000)


if __name__ == "__main__":
    unittest.main()
