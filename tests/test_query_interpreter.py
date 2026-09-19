import pytest

from src.agent.query_interpreter import QueryInterpreter
from src.models.criteria import SearchCriteria


class FakeResult:
    def __init__(self, output):
        self.output = output


class FakeAgent:
    def __init__(self, output):
        self.output = output
        self.request = None

    def run_sync(self, request):
        self.request = request
        return FakeResult(self.output)


def test_interpret_returns_search_criteria(monkeypatch):
    interpreter = QueryInterpreter()
    fake = FakeAgent(SearchCriteria(industry="crude oil", geography="Asia", roles=["buyer"]))
    monkeypatch.setattr(interpreter, "_get_agent", lambda: fake)
    result = interpreter.interpret("crude oil buyers in Asia")
    assert result.industry == "crude oil"
    assert result.geography == "Asia"
    assert result.roles == ["buyer"]
    assert fake.request == "crude oil buyers in Asia"


def test_empty_request_rejected():
    with pytest.raises(ValueError, match="cannot be empty"):
        QueryInterpreter().interpret("  ")


def test_missing_groq_key_is_explicit(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        QueryInterpreter().interpret("gold mining companies in Nigeria")
