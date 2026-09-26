"""Validate the submitted commit and compare it with its unchanged base."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

CONFIG = json.loads(Path(__file__).with_name("config.json").read_text())
SOURCE = Path(sys.argv[1]).resolve()
EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"
EVIDENCE.mkdir(exist_ok=True)
PYTHON = sys.executable
ENV = os.environ.copy()
ENV.pop("PYTHONPATH", None)
ENV["PYTHONDONTWRITEBYTECODE"] = "1"


def run(name, arguments, cwd=SOURCE, expected=0, contains=None):
    result = subprocess.run(arguments, cwd=cwd, env=ENV,
                            capture_output=True, text=True, timeout=240)
    text = result.stdout + result.stderr
    (EVIDENCE / (name + ".log")).write_text(text)
    assert result.returncode == expected, text[-9000:]
    if contains:
        assert contains in text, text[-9000:]
    print(name, "PASS" if expected == 0 else "EXPECTED FAILURE", flush=True)
    return text


def clear_bytecode():
    for directory in SOURCE.rglob("__pycache__"):
        shutil.rmtree(directory)


assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE,
                               text=True).strip() == CONFIG["sha"]
clear_bytecode()
run("submitted-suite", [PYTHON] + CONFIG["suite"], contains=CONFIG["suite_marker"])
run("source-lint", [PYTHON, "-m", "flake8", CONFIG["source"], "--select=E9,F63,F7,F82"])
run("test-lint", [PYTHON, "-m", "flake8", CONFIG["test"], "--max-line-length=119"])
path = SOURCE / CONFIG["source"]
fixed = path.read_bytes()
try:
    path.write_bytes(subprocess.check_output(["git", "show", CONFIG["base"] + ":" + CONFIG["source"]], cwd=SOURCE))
    clear_bytecode()
    run("original-regressions", [PYTHON] + CONFIG["targeted"], expected=1,
        contains=CONFIG["original_marker"])
finally:
    path.write_bytes(fixed)
    clear_bytecode()
assert path.read_bytes() == fixed
run("restored-suite", [PYTHON] + CONFIG["suite"], contains=CONFIG["suite_marker"])
run("patch-check", ["git", "diff", "--check", CONFIG["base"] + "...HEAD"])
run("source-restoration", ["git", "diff", "--exit-code"])
run("package-build", [PYTHON, "-m", "build"] + CONFIG["build_args"] + ["--outdir", str(EVIDENCE / "dist")])
wheel = next((EVIDENCE / "dist").glob("*.whl"))
run("install-wheel", [PYTHON, "-m", "pip", "install", "--force-reinstall", "--no-deps", "--no-index", str(wheel)])
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / "test_installed.py"
    shutil.copyfile(SOURCE / CONFIG["test"], target)
    code = "from pathlib import Path; import " + CONFIG["module"] + " as module; print(module.__file__); assert Path(" + repr(str(SOURCE)) + ") not in Path(module.__file__).resolve().parents"
    run("installed-module-location", [PYTHON, "-c", code], cwd=directory)
    run("installed-wheel-tests", [PYTHON] + CONFIG["installed"], cwd=directory,
        contains=CONFIG["installed_marker"])
run("dependency-check", [PYTHON, "-m", "pip", "check"])
run("dependency-versions", [PYTHON, "-m", "pip", "freeze"])
(EVIDENCE / "submission.json").write_text(json.dumps(CONFIG, indent=2))
print(CONFIG["summary"], flush=True)
