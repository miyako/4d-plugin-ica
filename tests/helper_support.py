import sys

sys.dont_write_bytecode = True

import importlib.util
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github/scripts"
INTAKE = "2b94d2ab88113db7bd4d67365ea547cf62971e4a"
sys.path.insert(0, str(SCRIPTS))


def helper(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def original(path):
    return subprocess.run(
        ["git", "show", f"{INTAKE}:{path}"], cwd=ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def fixture(test):
    temporary = tempfile.TemporaryDirectory(prefix=".ica-offline-", dir=ROOT)
    test.addCleanup(temporary.cleanup)
    return Path(temporary.name)
