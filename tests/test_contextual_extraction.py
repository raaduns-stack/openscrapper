from src.extract.contextual import ContextualLeadExtractor


class FakeModel:
    def __init__(self, result):
        self.result = result

    def inference(self, *args, **kwargs):
        return self.result


def relation(head, relation, tail, score=0.95):
    return {
        "head": {"text": head, "type": "person", "entity_idx": 0},
        "tail": {"text": tail, "type": "company", "entity_idx": 1},
        "relation": relation,
        "score": score,
    }


def test_contextual_fallback_builds_lead_from_person_relations():
    extractor = ContextualLeadExtractor(generic_prefixes=set())
    extractor._model = FakeModel({
        "entities": [[
            {"text": "D Jaworowski", "label": "person", "score": 0.99},
            {"text": "CRNA", "label": "job_role", "score": 0.99},
            {"text": "Albany Medical College", "label": "company", "score": 0.99},
            {"text": "Albany, NY", "label": "location", "score": 0.99},
        ]],
        "relations": [[
            relation("D Jaworowski", "has_position", "CRNA"),
            relation("D Jaworowski", "works_at", "Albany Medical College"),
            relation("D Jaworowski", "located_in", "Albany, NY"),
        ]],
    })
    lead = extractor.extract({
        "title": "NIH research",
        "raw_text": "D Jaworowski · CRNA in Albany, New York. Research Director at Albany Medical College.",
    }, "https://example.test/paper")
    assert lead is not None
    assert lead.first_name == "D"
    assert lead.last_name == "Jaworowski"
    assert lead.position == "CRNA"
    assert lead.company_name == "Albany Medical College"
    assert lead.city == "Albany"
    assert lead.state == "NY"


def test_contextual_fallback_rejects_non_person_org_entity():
    extractor = ContextualLeadExtractor(generic_prefixes=set())
    extractor._model = FakeModel({
        "entities": [[
            {"text": "Nassau University Medical Center", "label": "person", "score": 0.99},
            {"text": "teaching hospital", "label": "job_role", "score": 0.99},
        ]],
        "relations": [[
            relation("Nassau University Medical Center", "has_position", "teaching hospital"),
        ]],
    })
    assert extractor.extract({
        "title": "Nassau University Medical Center",
        "raw_text": "A teaching hospital in East Meadow, NY.",
    }, "https://example.test/hospital") is None


def test_contextual_fallback_rejects_bad_phone_relation():
    extractor = ContextualLeadExtractor(generic_prefixes=set())
    extractor._model = FakeModel({
        "entities": [[
            {"text": "Pawan Sandhu", "label": "person", "score": 0.99},
            {"text": "19,2K+ views", "label": "phone", "score": 0.99},
        ]],
        "relations": [[
            relation("Pawan Sandhu", "has_phone", "19,2K+ views"),
        ]],
    })
    assert extractor.extract({
        "title": "Registered Nurse Salary",
        "raw_text": "Pawan Sandhu video with 19,2K+ views.",
    }, "https://example.test/video") is None
