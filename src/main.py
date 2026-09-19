"""Legacy entry point retained for compatibility.

V1.2 application flow is SearchCriteria -> LeadDiscoveryPipeline.
Direct OpenClaw use is intentionally prohibited here.
"""

from src.cli import main


if __name__ == "__main__":
    main()
