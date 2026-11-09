"""
Tests that requests which cannot use an agent harness skip checking the agent CLIs (~10 s cold),
and that the discovery cache and registry stay consistent when they do.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from emiliano.core.capabilities import Capability, CapabilityStatus, ExecutionType
from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.core.registry import CapabilityRegistry

OLLAMA = Capability(name="ollama", display_name="Ollama (Local)", execution_type=ExecutionType.DIRECT_MODEL,
                    status=CapabilityStatus.READY, selected_model="qwen3.5:2b")
CODEX = Capability(name="codex", display_name="Codex", execution_type=ExecutionType.AGENT_HARNESS,
                   status=CapabilityStatus.READY)


def discovered_with(dispatcher, **route_args):
    """Routes once and returns the include_harnesses value discovery was called with."""
    with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock,
                      return_value={"ollama": OLLAMA, "codex": CODEX}) as discover:
        try:
            asyncio.run(dispatcher.route_task("hi", **route_args))
        except RuntimeError:
            pass  # e.g. the api policy with no remote provider; only the discovery scope matters here
    return discover.await_args.kwargs["include_harnesses"]


class TestDiscoveryScope(unittest.TestCase):
    def test_agent_clis_checked_only_when_a_harness_could_answer(self):
        cases = [
            ({}, True),                                   # auto: the goal might need an agent
            ({"harness_override": "codex"}, True),
            ({"policy": "harness"}, True),
            ({"provider_override": "ollama"}, False),
            ({"policy": "local"}, False),
            ({"policy": "api"}, False),
        ]
        for args, expected in cases:
            with self.subTest(**args):
                self.assertEqual(discovered_with(ExecutionDispatcher(), **args), expected)

    def test_recent_full_discovery_serves_direct_requests(self):
        dispatcher = ExecutionDispatcher()
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock,
                          return_value={"ollama": OLLAMA, "codex": CODEX}) as discover:
            asyncio.run(dispatcher.route_task("hi"))                           # full discovery
            asyncio.run(dispatcher.route_task("hi", provider_override="ollama"))  # reuses it
            asyncio.run(dispatcher.route_task("hi", policy="local"))
        self.assertEqual(discover.await_count, 1)

    def test_direct_discovery_does_not_serve_harness_requests(self):
        dispatcher = ExecutionDispatcher()
        with patch.object(dispatcher.registry, "discover_all", new_callable=AsyncMock,
                          return_value={"ollama": OLLAMA}) as discover:
            asyncio.run(dispatcher.route_task("hi", policy="local"))
            with self.assertRaises(Exception):
                asyncio.run(dispatcher.route_task("hi", harness_override="codex"))  # not found in that discovery
        self.assertEqual([c.kwargs["include_harnesses"] for c in discover.await_args_list], [False, True])


class TestRegistryDirectOnly(unittest.TestCase):
    def test_direct_only_discovery_runs_no_agent_cli_and_keeps_known_harnesses(self):
        registry = CapabilityRegistry()
        with patch.object(registry, "_discover_ollama", new_callable=AsyncMock, return_value=OLLAMA), \
             patch.object(registry, "_discover_api_providers", return_value=[]), \
             patch.object(registry, "_discover_harnesses", new_callable=AsyncMock, return_value=[CODEX]) as harnesses:
            asyncio.run(registry.discover_all())
            caps = asyncio.run(registry.discover_all(include_harnesses=False))
        harnesses.assert_awaited_once()  # only the full discovery ran the agent CLIs
        self.assertEqual(set(caps), {"ollama"})
        self.assertEqual({c.name for c in registry.get_harnesses()}, {"codex"})


if __name__ == "__main__":
    unittest.main()
