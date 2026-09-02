from pathlib import Path
from typing import Iterable
import pandas as pd
from src.models.lead import Lead

def export_csv(leads: Iterable[Lead], path: str = "output/leads.csv") -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([lead.model_dump(mode="json") for lead in leads]).to_csv(output, index=False)
    return output
