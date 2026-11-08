"""Shared test setup: keep tests from writing task traces into the user's ~/.emiliano/traces.db."""

import os
import tempfile

os.environ.setdefault("EMILIANO_TRACES_DB", os.path.join(tempfile.mkdtemp(prefix="emiliano-tests-"), "traces.db"))
