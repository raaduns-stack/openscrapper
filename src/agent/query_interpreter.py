import os

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from src.models.criteria import SearchCriteria

load_dotenv()


class QueryInterpreter:
    """Translate customer language into validated SearchCriteria."""

    def __init__(self, model: str = "openai/gpt-oss-20b"):
        self.model = model
        self.agent = None

    def _get_agent(self):
        if self.agent is None:
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("Query interpretation unavailable: GROQ_API_KEY is not configured")
            self.agent = Agent(
                GroqModel(self.model, provider=GroqProvider(api_key=api_key)),
                output_type=SearchCriteria,
                retries=2,
                system_prompt=(
                    "Translate a customer's lead-generation request into SearchCriteria. "
                    "Extract industry, product, geography, target_type, roles, keywords, and max_leads. "
                    "Do not invent constraints. If a field is not stated, leave it empty or use the schema default. "
                    "When the request seeks people, interpret job functions and commercial roles such as buyer, "
                    "seller, trader, broker, importer, exporter, procurement manager, purchasing manager, director, "
                    "manager, and CEO as roles, not merely keywords, and set target_type to people. "
                    "When the request explicitly seeks companies or businesses, set target_type to companies. "
                    "If the request is genuinely ambiguous between people and companies, use both."
                ),
            )
        return self.agent

    def interpret(self, request: str) -> SearchCriteria:
        request = request.strip()
        if not request:
            raise ValueError("Search request cannot be empty")
        result = self._get_agent().run_sync(request)
        return result.output
