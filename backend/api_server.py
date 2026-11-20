"""Start the workspace API and serve the built React application."""

import os
import sys
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from backend.api.routes import WorkspaceHandler
from backend.repositories.artifacts import ArtifactStore
from backend.repositories.workspace_db import WorkspaceDB
from backend.services.accounts import AccountService
from backend.services.assets import AssetService
from backend.services.coach import CoachService
from backend.services.jobs import JobService
from backend.services.practice import PracticeService


def main():
    database = WorkspaceDB()
    store_path = Path(os.environ.get("PIANO_STORE", ROOT / "outputs" / "api")).resolve()
    artifacts = ArtifactStore(store_path, database)
    admin_username = os.environ.get("PIANO_ADMIN_USERNAME", "admin").strip().lower()
    accounts = AccountService(database, admin_username)
    admin = accounts.bootstrap_admin(os.environ.get("PIANO_ADMIN_PASSWORD"))
    if admin and os.environ.get("PIANO_IMPORT_LEGACY") == "1":
        artifacts.import_legacy(admin["id"])
    artifacts.mark_interrupted_jobs()

    assets = AssetService(artifacts, database)
    handler = partial(
        WorkspaceHandler, accounts=accounts, assets=assets, jobs=JobService(artifacts, assets, ROOT),
        coach=CoachService(database, artifacts), practice=PracticeService(database, artifacts),
        static_root=(ROOT / "frontend" / "dist" / "client").resolve(),
        secure_cookies=os.environ.get("PIANO_COOKIE_SECURE") == "1",
    )
    port = int(os.environ.get("PIANO_PORT", 8000))
    bind = os.environ.get("PIANO_BIND", "127.0.0.1")
    print(f"Piano API listening at {bind}:{port}", flush=True)
    ThreadingHTTPServer((bind, port), handler).serve_forever()


if __name__ == "__main__":
    main()
