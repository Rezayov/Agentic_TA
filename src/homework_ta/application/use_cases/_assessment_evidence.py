"""Deterministic evidence IDs for assessment requests and exact citation resolution."""

import json

from homework_ta.domain.models import Assessment, GradingInput, citation_quotes


class AssessmentEvidence:
    def __init__(self, grading_input: GradingInput, result_type: type[Assessment]) -> None:
        quotes = citation_quotes(grading_input)
        sources = [
            ("student_answer", grading_input.submission.answer),
            *((source.source_id, source.content) for source in grading_input.source_material),
        ]
        self.catalog = []
        for source_id, content in sources:
            for quote in quotes:
                if quote in content:
                    self.catalog.append(
                        {
                            "quote_id": f"q{len(self.catalog):05d}",
                            "source_id": source_id,
                            "quote": quote,
                        }
                    )
        self._by_id = {item["quote_id"]: item for item in self.catalog}
        self.schema = result_type.schema_for_input(grading_input)
        evidence = self.schema["$defs"]["Evidence"]
        del evidence["properties"]["quote"]
        evidence["properties"]["quote_id"] = {
            "type": "string",
            "enum": list(self._by_id),
            "description": "Citation catalog identifier corresponding to the claimed source_id.",
        }
        evidence["required"] = [
            "quote_id" if field == "quote" else field for field in evidence["required"]
        ]
        self.data_json = json.dumps(
            {
                "grading_input": grading_input.model_dump(mode="json"),
                "citation_catalog": self.catalog,
            },
            ensure_ascii=False,
        )

    def decode(self, content: str) -> str:
        payload = json.loads(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("criteria"), list):
            return content  # Pydantic provides the structural error.
        for criterion in payload["criteria"]:
            if not isinstance(criterion, dict) or not isinstance(criterion.get("evidence"), list):
                continue
            for evidence in criterion["evidence"]:
                if not isinstance(evidence, dict) or "quote_id" not in evidence:
                    continue  # Legacy in-memory Evidence remains subject to exact-source scoring.
                reference = evidence["quote_id"]
                if not isinstance(reference, str) or reference not in self._by_id:
                    raise ValueError("unknown evidence quote_id")
                item = self._by_id[reference]
                if evidence.get("source_id") != item["source_id"]:
                    raise ValueError("evidence quote_id does not belong to the claimed source_id")
                if "quote" in evidence:
                    raise ValueError("evidence must use quote_id without a separate quote")
                del evidence["quote_id"]
                evidence["quote"] = item["quote"]
        return json.dumps(payload, ensure_ascii=False)
