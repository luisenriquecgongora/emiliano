"""Shared test setup: keep tests from writing task traces into the user's ~/.emiliano/traces.db."""

import os
import tempfile

os.environ.setdefault("EMILIANO_TRACES_DB", os.path.join(tempfile.mkdtemp(prefix="emiliano-tests-"), "traces.db"))
# litellm's bundled model price list: tests that import litellm directly would otherwise download it (and retry
# for seconds when the network or its certificates fail)
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
