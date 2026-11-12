"""Fork-only validation using the wheel built from the exact source baseline."""

import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

import vllm

BASE = "be47189f37f6162991366ff6b91539f6e9d1f432"
repo = Path(__file__).resolve().parents[2]
package = Path(vllm.__file__).resolve().parent
assert package != repo / "vllm", package
target = package / "entrypoints/openai/responses/context.py"
relative = "vllm/entrypoints/openai/responses/context.py"
baseline = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=repo)
assert target.read_bytes() == baseline, "Wheel does not match baseline context.py"
fixed = (repo / relative).read_bytes()

with tempfile.TemporaryDirectory() as directory:
    runner = Path(directory) / "run_tests.py"
    runner.write_text(
        "import sys, vllm\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "import pytest\n"
        "raise SystemExit(pytest.main(sys.argv[1:]))\n"
    )
    test = repo / "tests/entrypoints/openai/responses/test_serving_responses.py"
    try:
        for label, source in (("baseline", baseline), ("fixed", fixed)):
            target.write_bytes(source)
            for cache in target.parent.glob("__pycache__/context.*.pyc"):
                cache.unlink()
            report = Path(directory) / f"{label}.xml"
            command = [
                sys.executable, str(runner), str(test),
                "-k", "mcp_allowlist_enforced_before_execution",
                "-v", "--tb=short", f"--junitxml={report}",
            ]
            print(f"=== {label}: {' '.join(command)} ===", flush=True)
            result = subprocess.run(command, cwd=directory, check=False)
            suites = ElementTree.parse(report).getroot()
            cases = suites.findall(".//testcase")
            failures = suites.findall(".//failure")
            assert len(cases) == 36, len(cases)
            assert not suites.findall(".//error")
            if label == "baseline":
                assert result.returncode == 1
                assert len(failures) == 12, len(failures)
                assert all("DID NOT RAISE" in failure.get("message", "") for failure in failures)
            else:
                assert result.returncode == 0
                assert not failures
        test = repo / "tests/entrypoints/openai/responses/test_mcp_tools.py"
        for label, source in (("baseline", baseline), ("fixed", fixed)):
            target.write_bytes(source)
            for cache in target.parent.glob("__pycache__/context.*.pyc"):
                cache.unlink()
            report = Path(directory) / f"{label}-e2e.xml"
            command = [
                sys.executable, str(runner),
                f"{test}::test_mcp_allowlist_rejects_model_generated_call",
                "-v", "-s", "--tb=short", f"--junitxml={report}",
            ]
            print(f"=== E2E {label}: {' '.join(command)} ===", flush=True)
            result = subprocess.run(command, cwd=directory, check=False)
            suites = ElementTree.parse(report).getroot()
            assert len(suites.findall(".//testcase")) == 1
            assert not suites.findall(".//error")
            failures = suites.findall(".//failure")
            if label == "baseline":
                assert result.returncode == 1
                assert len(failures) == 1
                assert "DID NOT RAISE" in failures[0].get("message", "")
            else:
                assert result.returncode == 0
                assert not failures
    finally:
        target.write_bytes(baseline)
