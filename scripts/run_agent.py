from dataclasses import asdict
import argparse
import json
import sys

from src.agents.deal_research_agent import DealResearchAgent
from src.database.connection import SessionLocal, init_db

YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
BOLD = "\033[1m"
RESET = "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI Deal Room planning agent.")
    parser.add_argument("--deal-id", help="Existing deal ID, e.g. d_orbit")
    parser.add_argument("--company", help="Company name, e.g. OrbitGrid AI")
    parser.add_argument("--website", help="Company website")
    parser.add_argument("--docs", nargs="*", help="Document paths. If omitted, inferred from data/documents.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of the formatted report.")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        result = DealResearchAgent(db).update_deal_intelligence(
            deal_id=args.deal_id,
            company_name=args.company,
            website=args.website,
            doc_paths=args.docs,
        )

    payload = asdict(result)
    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print_report(payload)


def print_report(payload: dict) -> None:
    print(f"{BOLD}Deal Intelligence Report{RESET}")
    print(f"Company: {payload['company_name']}")
    print(f"Deal: {payload['deal_id']}")
    print(f"Agent run: {payload['run_id']}")
    print(f"Tools used: {', '.join(payload['tools_used'])}")

    _section("Agent Plan", BOLD)
    for step in payload["plan"]:
        print(f"- {step['action']}: {step['reason']}")

    _section("Coverage Gaps", BOLD)
    for item in payload.get("coverage_gaps", []):
        if item["status"] != "accepted":
            print(f"- {item['field_name']}: {item['status']} [{item['priority']}] -> {item['next_step']}")

    _section("Source Strategy", BOLD)
    for item in payload.get("source_strategy", []):
        print(f"- {item['recommended_tool']}: {', '.join(item['fields'])} | {item['why']}")

    _section("Accepted Facts", GREEN)
    for fact in payload["accepted_facts"]:
        print(_format_fact(fact))

    _section("Computed Metrics", GREEN)
    for metric in payload["computed_metrics"]:
        color = YELLOW if metric["review_status"] == "review_required" else ""
        suffix = RESET if color else ""
        flags = f", flags: {', '.join(metric['quality_flags'])}" if metric["quality_flags"] else ""
        print(
            f"{color}- {metric['metric_name']}: {metric['value']} "
            f"({metric['formula']}, confidence {metric['confidence_score']}, "
            f"{metric['review_status']}, {metric['staleness_status']}{flags}){suffix}"
        )

    _section("Low Confidence", YELLOW)
    if not payload["low_confidence_facts"]:
        print("- None")
    for fact in payload["low_confidence_facts"]:
        print(f"{YELLOW}{_format_fact(fact)}{RESET}")

    _section("Stale Metrics", YELLOW)
    if not payload["stale_metrics"]:
        print("- None")
    for metric in payload["stale_metrics"]:
        print(f"{YELLOW}- {metric['metric_name']}: {metric['value']} as of {metric['as_of_date']}{RESET}")

    _section("Conflicts", RED)
    if not payload["conflicts"]:
        print("- None")
    for conflict in payload["conflicts"]:
        print(f"{RED}- {conflict['field_name']} ({conflict['severity']}): facts {', '.join(conflict['fact_ids'])}{RESET}")

    _section("Review Items", YELLOW)
    if not payload["review_items"]:
        print("- None")
    for item in payload["review_items"]:
        print(f"{YELLOW}- {item['field_name']} [{item['priority']}]: {item['reason']}{RESET}")

    _section("Citations", BOLD)
    for citation in payload["citations"][:12]:
        evidence = citation["quoted_evidence"]
        label = citation["source_label"]
        print(f"- {citation['field_name']} | {label}: {evidence}")
    if len(payload["citations"]) > 12:
        print(f"- ... {len(payload['citations']) - 12} more citations")


def _section(title: str, color: str) -> None:
    print()
    print(f"{color}{title}{RESET}")


def _format_fact(fact: dict) -> str:
    value = fact["value"]
    if fact["currency"] == "USD" and isinstance(value, int | float):
        value = f"${value:,.0f}"
    elif fact["unit"] and fact["unit"] not in str(value):
        value = f"{value} {fact['unit']}"
    return (
        f"- {fact['field_name']}: {value} "
        f"(confidence {fact['confidence_score']}, {fact['review_status']}, {fact['staleness_status']})"
    )


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
