"""Portable source-checkout launcher, including non-ASCII paths."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "helpdesk_agent.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        workers=1,
    )
