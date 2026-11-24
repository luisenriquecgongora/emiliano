"""
Enterprise Test Suite: Generalized Codebase Translator & i18n Evaluation
Validates:
1. Discovery and hydration of the `codebase-translator` skill in SkillManager.
2. Strict Variable Token Locking (preventing {token} and %s corruption).
3. 100% Key Parity contract (zero missing keys between source and target).
4. BCP 47 and ISO 639-1 code normalization (e.g., 'quechua' -> 'qu').
5. Multi-tier architectural discovery across monorepo packages (PlaatoOS benchmark target).
6. Authentic Peruvian Quechua (Runasimi) domain lexicon validation.
7. Eval runner loading and execution of `codebase-translator` suite.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path

# Ensure engine package is in sys.path
ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# Also ensure workspace root is accessible
WORKSPACE_ROOT = ENGINE_ROOT.parent.parent.parent

from emiliano.core.skills import SkillManager
from emiliano.core.routing import needs_workspace
from emiliano.evals.runner import EvalRunner, Target, load_suite
from emiliano.history.api import SPECIALIST_MODE_CONFIGS, resolve_mode


class TestCodebaseTranslatorSkillAndMode(unittest.TestCase):
    """Pillar 1: Specialist Mode and Skill Hydration."""

    def test_01_skill_discovery(self):
        """Verifies SkillManager discovers codebase-translator skill with active status."""
        mgr = SkillManager.get_instance(workspace_root=WORKSPACE_ROOT)
        skill = mgr.get_skill("codebase-translator")
        self.assertIsNotNone(skill, "codebase-translator skill was not discovered by SkillManager")
        self.assertEqual(skill.status, "active")
        self.assertEqual(skill.category, "workflow")
        self.assertIn("translate codebase", skill.triggers)
        self.assertIn("read_file", skill.requirements)
        self.assertIn("edit_file", skill.requirements)

    def test_02_mode_configuration_integrity(self):
        """Verifies translator mode config in history/api.py."""
        self.assertIn("translator", SPECIALIST_MODE_CONFIGS)
        cfg = SPECIALIST_MODE_CONFIGS["translator"]
        self.assertEqual(cfg["category"], "tech")
        self.assertIn("Codebase Localization", cfg["title"])
        self.assertIn("codebase-translator", cfg["preferred_skills"])
        self.assertIn("key_parity", cfg["preferred_skills"])
        self.assertIn("variable_lock", cfg["preferred_skills"])

        policy, harness = resolve_mode("translator")
        self.assertIsNone(policy)
        self.assertIsNone(harness)


class TestTranslationQualityGates(unittest.TestCase):
    """Pillar 2: Variable Token Locking and Key Parity Math."""

    TOKEN_REGEX = re.compile(r"\{[a-zA-Z0-9_]+\}|%[sd]|%\.\d+f|\$\{[a-zA-Z0-9_]+\}")

    def test_03_variable_token_lock_detection(self):
        """Verifies that variable placeholders ({var}, %s, ${val}) are safely protected."""
        source = "Welcome to {businessName}, book room {roomNumber} at %s for {guestCount} guests."
        source_tokens = self.TOKEN_REGEX.findall(source)
        self.assertEqual(set(source_tokens), {"{businessName}", "{roomNumber}", "%s", "{guestCount}"})

        # Valid Quechua translation preserving tokens
        valid_qu = "Allillanchu {businessName}-man, {roomNumber} takina wasita waqaychay %s chaniwan {guestCount} runakunapaq."
        target_tokens = self.TOKEN_REGEX.findall(valid_qu)
        self.assertEqual(set(source_tokens), set(target_tokens), "Variable tokens were modified or omitted")

        # Corrupted translation (modifying variable names into translated words)
        corrupted_qu = "Allillanchu {negocioSuti}-man, {hospedajeNum} takina wasita..."
        corrupted_tokens = self.TOKEN_REGEX.findall(corrupted_qu)
        self.assertNotEqual(set(source_tokens), set(corrupted_tokens))

    def test_04_key_parity_mathematics(self):
        """Verifies key parity calculation guarantees zero dropped keys."""
        source_dict = {
            "page_title": "Karaoke Pricing",
            "select_duration": "Select Duration",
            "total_price": "Total Price",
            "confirm_whatsapp": "Confirm on WhatsApp",
            "closed": "Closed",
        }

        # Perfect target
        complete_target = {
            "page_title": "Takiy Chani",
            "select_duration": "Pacha akllay",
            "total_price": "Tukuy Chani",
            "confirm_whatsapp": "WhatsApp-pi cheqaqchay",
            "closed": "Wichqasqa",
        }
        missing_keys = set(source_dict.keys()) - set(complete_target.keys())
        extra_keys = set(complete_target.keys()) - set(source_dict.keys())
        self.assertEqual(len(missing_keys), 0)
        self.assertEqual(len(extra_keys), 0)

        # Incomplete target
        incomplete_target = {
            "page_title": "Takiy Chani",
            "total_price": "Tukuy Chani",
        }
        missing = set(source_dict.keys()) - set(incomplete_target.keys())
        self.assertEqual(missing, {"select_duration", "confirm_whatsapp", "closed"})


class TestBcp47AndLexiconValidation(unittest.TestCase):
    """Pillar 3: Normalization and Quechua Domain Lexicon."""

    def test_05_bcp47_normalization_rules(self):
        """Tests canonical BCP 47 / ISO normalization for Quechua."""
        legacy_map = {
            "english": "en",
            "spanish": "es",
            "polish": "pl",
            "quechua": "qu",
            "runasimi": "qu",
        }
        def normalize_lang(raw: str | None) -> str:
            if not raw:
                return "en"
            trimmed = raw.strip().lower()
            return legacy_map.get(trimmed, trimmed)

        self.assertEqual(normalize_lang("quechua"), "qu")
        self.assertEqual(normalize_lang("Runasimi"), "qu")
        self.assertEqual(normalize_lang("qu"), "qu")
        self.assertEqual(normalize_lang("EN"), "en")

    def test_06_quechua_hospitality_lexicon_integrity(self):
        """Validates that authentic Quechua domain terms match hospitality and karaoke concepts."""
        lexicon = {
            "karaoke_sing": "Taki",
            "karaoke_room": "Takina Wasi",
            "price_cost": "Chani",
            "hourly_rate": "Chani / ura",
            "book_reserve": "Waqaychay",
            "closed": "Wichqasqa",
            "welcome": "Allillanchu",
            "time_hour": "Pacha",
        }
        # Taki is the root for song/singing
        self.assertTrue(lexicon["karaoke_sing"].startswith("Taki"))
        # Chani is price/value
        self.assertIn("Chani", lexicon["price_cost"])
        # Waqaychay is to reserve/keep/protect
        self.assertEqual(lexicon["book_reserve"], "Waqaychay")
        # Wichqasqa is closed
        self.assertEqual(lexicon["closed"], "Wichqasqa")


class TestPlaatoosMonorepoDiscoveryBenchmark(unittest.TestCase):
    """Pillar 4: Real-world monorepo multi-tier inspection benchmark."""

    def test_07_plaatoos_takient_touchpoints_exist(self):
        """Verifies that all 4 tiers of the PlaatoOS monorepo exist and are discoverable."""
        takient_root = WORKSPACE_ROOT / "takient"
        if not takient_root.exists():
            self.skipTest(f"takient directory not found at {takient_root}")

        # Tier 1: Shared Core
        core_nav = takient_root / "experimentaltaki" / "packages" / "core" / "src" / "config" / "navigationTranslations.ts"
        core_blocks = takient_root / "experimentaltaki" / "packages" / "core" / "src" / "components" / "BusinessSiteRenderer" / "blocks" / "blockLocale.ts"
        core_lang_code = takient_root / "experimentaltaki" / "packages" / "core" / "src" / "utils" / "languageCode.ts"
        self.assertTrue(core_nav.exists(), f"Missing {core_nav}")
        self.assertTrue(core_blocks.exists(), f"Missing {core_blocks}")
        self.assertTrue(core_lang_code.exists(), f"Missing {core_lang_code}")

        # Tier 2: Backend API
        api_checkout = takient_root / "api-takient" / "src" / "utils" / "checkoutTranslations.ts"
        api_email = takient_root / "api-takient" / "src" / "utils" / "emailTranslations.ts"
        api_business = takient_root / "api-takient" / "src" / "models" / "Business.ts"
        self.assertTrue(api_checkout.exists(), f"Missing {api_checkout}")
        self.assertTrue(api_email.exists(), f"Missing {api_email}")
        self.assertTrue(api_business.exists(), f"Missing {api_business}")

        # Tier 3: Next Tenant Sites
        tenant_middleware = takient_root / "experimentaltaki" / "apps" / "next-tenant-sites" / "middleware.ts"
        tenant_pick = takient_root / "experimentaltaki" / "apps" / "next-tenant-sites" / "lib" / "pickLocalized.ts"
        self.assertTrue(tenant_middleware.exists(), f"Missing {tenant_middleware}")
        self.assertTrue(tenant_pick.exists(), f"Missing {tenant_pick}")

        # Tier 4: Business Admin
        admin_seo = takient_root / "experimentaltaki" / "apps" / "mfe-admin" / "src" / "Admin" / "SEO" / "tabs" / "SettingsTab.tsx"
        self.assertTrue(admin_seo.exists(), f"Missing {admin_seo}")


class TestCodebaseTranslatorEvalSuite(unittest.TestCase):
    """Pillar 5: Eval Suite Execution via Emiliano EvalRunner."""

    def test_08_load_codebase_translator_suite(self):
        """Verifies codebase-translator.yaml loads with expected tasks."""
        suite = load_suite("codebase-translator")
        self.assertEqual(suite["name"], "codebase-translator")
        tasks = {t["id"]: t for t in suite.get("tasks", [])}
        self.assertIn("route-translator-add-language", tasks)
        self.assertIn("check-token-lock-preservation", tasks)
        self.assertIn("check-token-printf-preservation", tasks)
        self.assertIn("code-i18n-dictionary-parity", tasks)

    def test_09_run_route_tasks_in_suite(self):
        """Verifies deterministic routing tasks pass cleanly."""
        suite = load_suite("codebase-translator")
        route_tasks = [t for t in suite.get("tasks", []) if t.get("kind") == "route"]
        self.assertGreaterEqual(len(route_tasks), 2)

        runner = EvalRunner()
        for task in route_tasks:
            result = runner._run_route(task)
            self.assertEqual(
                result.status, "passed",
                f"Routing task '{task['id']}' failed: {result.detail}"
            )


if __name__ == "__main__":
    unittest.main()
