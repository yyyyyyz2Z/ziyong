"""Shared Audiveris adapter used by the main site and research workbench."""

# Keep subprocess available for existing recognition tests and integrations.
import subprocess
from backend.analysis.score_recognition import (
    MUSICXML_EXTENSIONS, MISSING_AUDIVERIS, find_audiveris, recognize_pdf,
)
