import json
from pathlib import Path
from dataclasses import dataclass

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "geography"

@dataclass(frozen=True)
class GeographyState:
    name: str
    state_id: int
    cities: list[str]

@dataclass(frozen=True)
class GeographyResult:
    country: str
    country_id: int | None
    states: list[GeographyState]

class GeographyResolver:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.countries = self._load("countriesminified.json")
        self.states = self._load("statesminified.json")
        self.cities = self._load("citiesminified.json")
        self._country_index = {str(c.get("name", "")).strip().casefold(): c for c in self.countries if c.get("name")}

    @staticmethod
    def _norm(value: str | None) -> str:
        return " ".join(str(value or "").split()).strip().casefold()

    def classify(self, city: str | None = None, state: str | None = None, country: str | None = None) -> dict[str, str | None]:
        """Validate and canonicalize extracted location fields against the bundled geography data."""
        city, state, country = (str(x).strip() if x else None for x in (city, state, country))

        # A value occupying city/state can actually be a country.
        for value_name in ("country", "state", "city"):
            value = locals()[value_name]
            record = self._country_index.get(self._norm(value)) if value else None
            if record:
                country = record.get("name")
                if value_name != "country":
                    if value_name == "city": city = None
                    else: state = None
                break

        if not country:
            return {"city": city, "state": state, "country": country}

        country_record = self._country_index.get(self._norm(country))
        if not country_record:
            return {"city": city, "state": state, "country": country}
        country = country_record.get("name")
        country_id = country_record.get("id")

        state_record = next((r for r in self.states if r.get("id") == country_id), None)
        states = state_record.get("states", []) if state_record else []
        state_by_name = {self._norm(x.get("name")): x for x in states if x.get("name")}

        # Canonicalize state when supplied; reject an unverified state rather than inventing it.
        matched_state = state_by_name.get(self._norm(state)) if state else None
        if matched_state:
            state = str(matched_state.get("name")).strip()
        elif state:
            state = None

        city_record = next((r for r in self.cities if r.get("id") == country_id), None)
        city_states = city_record.get("states", []) if city_record else []
        state_city_lists = {x.get("id"): x.get("cities", []) for x in city_states}

        # Validate city within the matched state first, otherwise against all cities in country.
        matched_city = None
        if city:
            candidate_states = [matched_state] if matched_state else states
            for st in candidate_states:
                for item in state_city_lists.get(st.get("id"), []):
                    if self._norm(item.get("name")) == self._norm(city):
                        matched_city = item
                        break
                if matched_city:
                    if not matched_state:
                        state_obj = next((x for x in states if x.get("id") == st.get("id")), None)
                        state = str(state_obj.get("name")).strip() if state_obj and state_obj.get("name") else None
                    break
            if matched_city:
                city = str(matched_city.get("name")).strip()
            else:
                city = None

        return {"city": city, "state": state, "country": country}

    def _load(self, filename: str):
        with open(self.data_dir / filename, "r", encoding="utf-8") as f:
            return json.load(f)

    def resolve(self, country_name: str) -> GeographyResult:
        country = next(
            (
                c for c in self.countries
                if str(c.get("name", "")).strip().lower()
                == country_name.strip().lower()
            ),
            None,
        )

        if not country:
            raise ValueError(f"Unknown country: {country_name}")

        country_id = country.get("id")

        state_record = next(
            (r for r in self.states if r.get("id") == country_id),
            None,
        )

        country_states = state_record.get("states", []) if state_record else []

        city_record = next(
            (r for r in self.cities if r.get("id") == country_id),
            None,
        )

        city_states = {
            state.get("id"): state.get("cities", [])
            for state in (city_record.get("states", []) if city_record else [])
        }

        states = []

        for state in country_states:
            state_id = state.get("id")
            state_name = state.get("name")

            if not state_name or state_id is None:
                continue

            cities = sorted({
                str(city["name"]).strip()
                for city in city_states.get(state_id, [])
                if city.get("name")
            })

            states.append(
                GeographyState(
                    name=str(state_name).strip(),
                    state_id=state_id,
                    cities=cities,
                )
            )

        return GeographyResult(
            country=country.get("name", country_name),
            country_id=country_id,
            states=sorted(states, key=lambda x: x.name),
        )
