import os
from pathlib import Path
import subprocess

import yaml


ACTION = Path(__file__).parents[1] / "action.yml"


def action_steps():
    return yaml.safe_load(ACTION.read_text())["runs"]["steps"]


def step_script(name: str) -> str:
    return next(step["run"] for step in action_steps() if step.get("name") == name)


def write_executable(path: Path, script: str) -> None:
    path.write_text(script)
    path.chmod(0o755)


def run_system_tool_step(tmp_path: Path, *, include_gh: bool, include_jq: bool):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo_log = tmp_path / "sudo.log"

    if include_gh:
        write_executable(bin_dir / "gh", "#!/bin/sh\necho 'gh version test'\n")
    if include_jq:
        write_executable(bin_dir / "jq", "#!/bin/sh\necho 'jq-test'\n")

    # Mock apt. Installing a missing package creates the executable so the
    # action's post-install version checks also exercise the complete path.
    write_executable(
        bin_dir / "sudo",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$SUDO_LOG"
if [ "$1" = "apt-get" ] && printf '%s\\n' "$*" | grep -q 'install -y'; then
  for package in gh jq; do
    if printf '%s\\n' "$*" | grep -q " $package"; then
      printf '#!/bin/sh\\necho %s-test\\n' "$package" > "$MOCK_BIN/$package"
      chmod +x "$MOCK_BIN/$package"
    fi
  done
fi
""",
    )

    env = os.environ | {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "SUDO_LOG": str(sudo_log),
        "MOCK_BIN": str(bin_dir),
    }
    result = subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", step_script("Ensure required system tools")],
        env=env,
        capture_output=True,
        text=True,
    )
    return result, sudo_log.read_text() if sudo_log.exists() else ""


def test_preinstalled_tools_skip_apt(tmp_path):
    result, sudo_calls = run_system_tool_step(tmp_path, include_gh=True, include_jq=True)

    assert result.returncode == 0, result.stderr
    assert sudo_calls == ""


def test_missing_tool_uses_bounded_apt_fallback(tmp_path):
    result, sudo_calls = run_system_tool_step(tmp_path, include_gh=False, include_jq=True)

    assert result.returncode == 0, result.stderr
    assert sudo_calls.count("apt-get") == 2
    assert "Acquire::Retries=3" in sudo_calls
    assert "Acquire::http::Timeout=20" in sudo_calls
    assert "Acquire::https::Timeout=20" in sudo_calls
    assert "install -y gh" in sudo_calls
    assert "install -y jq" not in sudo_calls
