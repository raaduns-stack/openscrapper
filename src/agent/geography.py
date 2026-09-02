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
