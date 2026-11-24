import os
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JBUILD_ROOT = PROJECT_ROOT / "journey-builder"
if str(JBUILD_ROOT) not in sys.path:
    sys.path.insert(0, str(JBUILD_ROOT))


from jbuild.cli.main import cli


def test_click_cli_exposes_expected_command_groups():
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "trait-classifiers" in result.output
    assert "traits" in result.output


def test_nested_trait_commands_are_wired():
    runner = CliRunner()

    traits_result = runner.invoke(cli, ["traits", "--help"])
    values_result = runner.invoke(cli, ["traits", "values", "--help"])
    classifiers_result = runner.invoke(cli, ["trait-classifiers", "--help"])

    assert traits_result.exit_code == 0
    assert "create" in traits_result.output
    assert "values" in traits_result.output
    assert values_result.exit_code == 0
    assert "set" in values_result.output
    assert classifiers_result.exit_code == 0
    assert "draft" in classifiers_result.output
    assert "activate" in classifiers_result.output


def test_module_cli_help_works_with_journey_builder_pythonpath():
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{JBUILD_ROOT}:{env.get('PYTHONPATH', '')}"

    result = subprocess.run(
        [sys.executable, "-m", "jbuild.cli.main", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "Headless jbuild CLI" in result.stdout


def test_root_jbuild_wrapper_reaches_cli_help():
    result = subprocess.run(
        [str(PROJECT_ROOT / "jbuild"), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "Headless jbuild CLI" in result.stdout
