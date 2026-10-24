"""Tests for action.yml structure and conditional dependency installation."""

from pathlib import Path
import unittest
import yaml


class TestActionYaml(unittest.TestCase):
    """Validate action.yml configuration and conditional install logic."""

    @classmethod
    def setUpClass(cls):
        cls.action_path = Path(__file__).resolve().parent.parent / "action.yml"
        with open(cls.action_path, "r", encoding="utf-8") as f:
            cls.action = yaml.safe_load(f)

    def test_action_yml_is_valid_composite(self):
        self.assertEqual(self.action.get("runs", {}).get("using"), "composite")
        self.assertIn("steps", self.action.get("runs", {}))

    def test_gh_cli_install_checks_existing_binary(self):
        steps = self.action["runs"]["steps"]
        gh_step = next(
            (s for s in steps if s.get("name") == "Install GitHub CLI"), None
        )
        self.assertIsNotNone(gh_step, "Install GitHub CLI step must exist")
        run_script = gh_step.get("run", "")
        self.assertIn("command -v gh", run_script)
        self.assertIn("sudo apt-get update && sudo apt-get install -y gh", run_script)
        self.assertIn("skipping install", run_script)

    def test_jq_install_checks_existing_binary(self):
        steps = self.action["runs"]["steps"]
        dep_step = next(
            (s for s in steps if s.get("name") == "Install dependencies"), None
        )
        self.assertIsNotNone(dep_step, "Install dependencies step must exist")
        run_script = dep_step.get("run", "")
        self.assertIn("command -v jq", run_script)
        self.assertIn("sudo apt-get update && sudo apt-get install -y jq", run_script)
        self.assertIn("skipping install", run_script)


if __name__ == "__main__":
    unittest.main()
