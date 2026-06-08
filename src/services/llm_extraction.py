from datetime import date
import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from src.config import load_env_file
from src.parsers.document_parser import ExtractedFact, parse_as_of_date

SUPPORTED_LLM_FIELDS = {
    "arr",
    "monthly_burn",
    "target_raise",
    "pre_money_valuation",
    "post_money_valuation",
    "investment_amount",
    "headcount",
    "revenue_growth_pct",
    "gross_margin_pct",
    "runway_months",
    "headquarters",
    "round",
    "lead_investor",
}


class LLMExtractionService:
    def __init__(self) -> None:
        load_env_file()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def extract_missing_facts(self, text: str, missing_fields: set[str]) -> list[ExtractedFact]:
        if not self.enabled or not missing_fields:
            return []

        prompt = _build_prompt(text, sorted(missing_fields))
        response_text = self._call_gemini_text(prompt)
        payload = _parse_json_response(response_text)
        return _facts_from_payload(payload, fallback_as_of_date=parse_as_of_date(text), method="gemini_flash_fallback", confidence_score=0.74)

    def extract_image_facts(self, path: str | Path, target_fields: set[str]) -> list[ExtractedFact]:
        if not self.enabled or not target_fields:
            return []

        file_path = Path(path)
        prompt = _build_image_prompt(sorted(target_fields), file_path.name)
        response_text = self._call_gemini_image(prompt, file_path)
        payload = _parse_json_response(response_text)
        return _facts_from_payload(payload, fallback_as_of_date=None, method="gemini_flash_vision", confidence_score=0.72)

    def _call_gemini_text(self, prompt: str) -> str:
        return self._call_gemini_parts([{"text": prompt}])

    def _call_gemini_image(self, prompt: str, file_path: Path) -> str:
        mime_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
        image_data = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return self._call_gemini_parts(
            [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": image_data}},
            ]
        )

    def _call_gemini_parts(self, parts: list[dict]) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini extraction failed: {exc}") from exc

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Gemini response did not include extractable text: {data}") from exc


def _build_prompt(text: str, missing_fields: list[str]) -> str:
    fields = ", ".join(missing_fields)
    return f"""
You extract structured diligence facts for an early-stage venture investment associate.

Return JSON only, with this exact shape:
{{
  "facts": [
    {{
      "field_name": "arr",
      "value_text": "$12.4M",
      "value_numeric": 12400000,
      "unit": null,
      "currency": "USD",
      "as_of_date": "2026-03-31",
      "quoted_evidence": "ARR: $12.4M as of Q1 2026",
      "review_reason": "llm_fallback"
    }}
  ]
}}

Only extract these missing fields: {fields}.
Only include a fact if the document text directly supports it.
Do not infer a value that is not stated or tightly paraphrased.
Normalize money values into full numeric USD values when possible.
Use null for unknown dates, units, currency, value_text, or value_numeric.
The quoted_evidence must be an exact short quote from the document.

Document:
\"\"\"
{text}
\"\"\"
""".strip()


def _build_image_prompt(target_fields: list[str], filename: str) -> str:
    fields = ", ".join(target_fields)
    return f"""
You extract structured diligence facts from an uploaded image for an early-stage venture investment associate.
The image may be an email screenshot, handwritten note, slide screenshot, or other deal material.

Return JSON only, with this exact shape:
{{
  "facts": [
    {{
      "field_name": "round",
      "value_text": "Series A",
      "value_numeric": null,
      "unit": null,
      "currency": null,
      "as_of_date": null,
      "quoted_evidence": "short visible text from the image",
      "review_reason": "vision_extraction"
    }}
  ]
}}

Only extract these target fields: {fields}.
Only include facts that are visible in the image.
Do not infer hidden context from the company name or filename.
Use null when a normalized numeric value, currency, unit, or date is unavailable.
For money values, normalize value_numeric into full USD when the image clearly indicates dollars.
The quoted_evidence should be the shortest visible text that supports the fact.

Filename: {filename}
""".strip()


def _parse_json_response(response_text: str) -> dict:
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not match:
            return {"facts": []}
        return json.loads(match.group(0))


def _facts_from_payload(
    payload: dict,
    fallback_as_of_date: date | None,
    method: str,
    confidence_score: float,
) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    for item in payload.get("facts", []):
        field_name = item.get("field_name")
        if field_name not in SUPPORTED_LLM_FIELDS:
            continue
        evidence = item.get("quoted_evidence")
        if not evidence:
            continue

        as_of_date = fallback_as_of_date
        if item.get("as_of_date"):
            try:
                as_of_date = date.fromisoformat(item["as_of_date"])
            except ValueError:
                as_of_date = fallback_as_of_date

        facts.append(
            ExtractedFact(
                field_name=field_name,
                value_text=item.get("value_text"),
                value_numeric=_float_or_none(item.get("value_numeric")),
                unit=item.get("unit"),
                currency=item.get("currency"),
                as_of_date=as_of_date,
                evidence=evidence,
                confidence_score=confidence_score,
                extraction_method=method,
            )
        )
    return facts


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
