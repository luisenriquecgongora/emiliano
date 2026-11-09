"""
Tests for deciding whether a goal needs an agent harness (emiliano/core/routing.py), one rule at a time.
The routing eval suite (`emiliano eval routing`) measures the rules on many more goals.
"""

import unittest

from emiliano.core.dispatcher import ExecutionDispatcher
from emiliano.core.routing import mentions_file, needs_workspace
from emiliano.evals.runner import load_suite


class TestRules(unittest.TestCase):
    def check(self, goals, expected):
        for goal in goals:
            with self.subTest(goal=goal):
                self.assertEqual(needs_workspace(goal), expected)

    def test_a_files_and_paths(self):
        self.assertTrue(mentions_file("Update the version in package.json"))
        self.assertTrue(mentions_file("Look at src/ and summarize"))
        self.assertTrue(mentions_file("fix tests/test_api.py"))
        for not_a_file in ("What is a .gitignore file for?", "How do I learn Node.js?", "Version 2.0 is out",
                           "TCP and/or UDP", "See example.com"):
            with self.subTest(text=not_a_file):
                self.assertFalse(mentions_file(not_a_file))

    def test_b_own_work(self):
        self.check(["What does this code do?", "Commit my changes", "¿Puedes revisar este proyecto?"], True)

    def test_c_command_about_a_specific_thing(self):
        self.check(["Install the dependencies", "Ejecuta los tests", "Write tests for the parser module",
                    "Can you check if the tests pass?", "Run tests"], True)
        # A request for a new snippet or text is not about the workspace
        self.check(["Write a Python function that reverses a string", "Write a haiku about rain",
                    "Escribe un poema corto sobre el mar", "Summarize the plot of Hamlet"], False)

    def test_d_something_broken(self):
        self.check(["Why is the build failing?", "¿Por qué no funciona el servidor?"], True)

    def test_questions_stay_direct(self):
        self.check(["How do I write a unit test in pytest?", "What does npm install do?",
                    "Explain the difference between git merge and git rebase", "¿Qué es una función recursiva?"],
                   False)

    def test_dispatcher_uses_the_rules(self):
        self.assertTrue(ExecutionDispatcher.requires_agent_harness("Delete the unused imports in main.py"))
        self.assertFalse(ExecutionDispatcher.requires_agent_harness("hi"))


class TestRoutingSuite(unittest.TestCase):
    def test_every_suite_goal_is_routed_as_labelled(self):
        # Regression guard: a rule change must not break a goal the suite already covers
        for task in load_suite("routing")["tasks"]:
            with self.subTest(task=task["id"]):
                got = "harness" if needs_workspace(task["goal"]) else "direct"
                self.assertEqual(got, task["expect"]["route"], task["goal"])


if __name__ == "__main__":
    unittest.main()
