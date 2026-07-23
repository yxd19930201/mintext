"""Production entry point for the independently packaged Mintext server."""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Mintext C/S server")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for LAN clients")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("LOCALAPPDATA", ".")) / "MintextServer")
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MINITEXT_DATA_DIR", str(args.data_dir))
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(args.data_dir / 'minitext.db').as_posix()}")
    os.environ.setdefault("APP_ENV", "production")
    os.environ.setdefault("DEBUG", "false")

    import uvicorn
    from app.main import app
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
