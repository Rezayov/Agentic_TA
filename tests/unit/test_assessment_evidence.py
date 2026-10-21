import json

import pytest
from jsonschema import ValidationError, validate
from test_workflow import FakeLLM, assessment_json, load_input

from homework_ta.application.use_cases._assessment_evidence import AssessmentEvidence
from homework_ta.application.use_cases.analyze_answer import AnalyzeAnswer
from homework_ta.domain.models import AnalystAssessment, SourceExcerpt, VerifierAssessment


def test_catalog_is_identical_for_independent_assessors_and_input_is_frozen():
    original = load_input()
    before = original.model_dump_json()
    analyst = AssessmentEvidence(original, AnalystAssessment)
    verifier = AssessmentEvidence(original, VerifierAssessment)
    assert analyst.catalog == verifier.catalog
    assert analyst.data_json == verifier.data_json
    assert original.model_dump_json() == before
    assert "quote" not in analyst.schema["$defs"]["Evidence"]["properties"]
    assert analyst.schema["$defs"]["Evidence"]["properties"]["quote_id"]["enum"]


def wire_response(evidence):
    payload = json.loads(assessment_json("analyst"))
    for criterion in payload["criteria"]:
        for item in criterion["evidence"]:
            match = next(
                entry
                for entry in evidence.catalog
                if entry["source_id"] == item["source_id"] and item["quote"] in entry["quote"]
            )
            del item["quote"]
            item["quote_id"] = match["quote_id"]
    return payload


def test_evidence_ids_resolve_to_original_quotes_and_pass_scoring():
    original = load_input()
    evidence = AssessmentEvidence(original, AnalystAssessment)
    payload = wire_response(evidence)
    validate(payload, evidence.schema)
    result = AnalyzeAnswer(FakeLLM([json.dumps(payload)]), "prompt").execute(original)
    assert result.total_awarded_points == 3
    assert all(
        item.quote in original.submission.answer
        for criterion in result.assessment.criteria
        for item in criterion.evidence
    )


def test_wrong_source_unknown_id_and_duplicate_quote_are_rejected():
    original = load_input().model_copy(
        update={
            "source_material": (
                SourceExcerpt(
                    source_id="ref",
                    location="page 1",
                    content="Reference content that is unrelated.",
                ),
            )
        }
    )
    evidence = AssessmentEvidence(original, AnalystAssessment)
    payload = wire_response(evidence)
    item = payload["criteria"][0]["evidence"][0]
    item["source_id"] = "ref"
    with pytest.raises(ValueError, match="claimed source"):
        evidence.decode(json.dumps(payload))
    item["source_id"] = "student_answer"
    item["quote_id"] = "invented"
    with pytest.raises(ValueError, match="unknown"):
        evidence.decode(json.dumps(payload))
    item["quote_id"] = next(
        entry["quote_id"] for entry in evidence.catalog if entry["source_id"] == "student_answer"
    )
    item["quote"] = "Invented extra quote"
    with pytest.raises(ValueError, match="without a separate quote"):
        evidence.decode(json.dumps(payload))


def test_wire_schema_rejects_free_text_quotes():
    evidence = AssessmentEvidence(load_input(), AnalystAssessment)
    with pytest.raises(ValidationError):
        validate(json.loads(assessment_json("analyst")), evidence.schema)
