"""Synthetic tests for caller-relative instruction file paths."""

import os
from pathlib import Path
import tempfile
import unittest

from claudecode.path_utils import resolve_instruction_path


class ResolveInstructionPathTests(unittest.TestCase):
    def test_relative_path_uses_repository_root_not_action_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / "caller-repository"
            action = root / "installed-action"
            instruction = repository / ".github" / "security-instructions.md"
            instruction.parent.mkdir(parents=True)
            instruction.write_text("synthetic instructions", encoding="utf-8")
            action.mkdir()

            original_cwd = Path.cwd()
            try:
                os.chdir(action)
                self.assertFalse(Path(".github/security-instructions.md").exists())
                resolved = resolve_instruction_path(
                    ".github/security-instructions.md", str(repository)
                )
                self.assertEqual(resolved, instruction)
                self.assertEqual(
                    resolved.read_text(encoding="utf-8"), "synthetic instructions"
                )
            finally:
                os.chdir(original_cwd)

    def test_absolute_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            absolute_path = Path(temp_dir) / "instructions.md"
            self.assertEqual(
                resolve_instruction_path(str(absolute_path), "another/repository"),
                absolute_path,
            )

    def test_without_repository_root_preserves_relative_path(self):
        relative_path = Path(".github/security-instructions.md")
        self.assertEqual(resolve_instruction_path(str(relative_path)), relative_path)

    def test_empty_path_stays_empty(self):
        self.assertEqual(resolve_instruction_path("", "repository"), Path("."))


if __name__ == "__main__":
    unittest.main()
