"""Проверка тестов четырьмя мутантами в отдельных временных копиях app, без правки исходников."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
backend = root / "backend"
base = Path(tempfile.mkdtemp(prefix="pgweb-mutants-"))
cases = [
    (
        "csrf",
        "main.py",
        'if request.method not in {"GET", "HEAD", "OPTIONS"}:',
        "if False:",
        "test_http_security.py::test_mutations_require_csrf",
    ),
    (
        "rbac",
        "services/admin.py",
        'if user.role != "admin":',
        "if False:",
        "test_admin.py::test_member_cannot_administer_even_by_direct_request",
    ),
    (
        "totp_replay",
        "core/security/totp.py",
        "if matched is None or (last_step is not None and matched <= last_step):",
        "if matched is None:",
        "test_security.py::test_totp_has_bounded_time_window_and_rejects_replay",
    ),
    (
        "admin_transaction_lock",
        "services/admin.py",
        (
            "await require_admin(db, request)\n"
            '    await db.execute(text("SELECT pg_advisory_xact_lock(74623019)"))\n'
            "    actor = await auth.current_user(db, request, touch=False)"
        ),
        (
            'await db.execute(text("SELECT pg_advisory_xact_lock(74623019)"))\n'
            "    actor = await require_admin(db, request)"
        ),
        "test_admin.py::test_two_admins_cannot_revoke_each_other_with_stale_sessions",
    ),
]
results = []
for name, filename, original, changed, target in cases:
    work = base / name
    shutil.copytree(backend / "app", work / "app", ignore=shutil.ignore_patterns("__pycache__"))
    path = work / "app" / filename
    content = path.read_text()
    assert original in content, name
    path.write_text(content.replace(original, changed, 1))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(work) + os.pathsep + str(backend)
    if not env.get("PGWEB_TEST_DATABASE_URL"):
        raise SystemExit("PGWEB_TEST_DATABASE_URL must point to a dedicated test database")
    check = subprocess.run(
        [sys.executable, "-c", "import app; print(app.__file__)"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(work / "app") in check.stdout, check.stdout
    output = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--import-mode=importlib",
            str(backend / "tests" / target),
            "-q",
            "--tb=short",
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    (work / "result.txt").write_text(output.stdout + output.stderr)
    killed = output.returncode == 1 and (
        "AssertionError" in output.stdout or "E   assert " in output.stdout
    )
    results.append(
        {
            "mutant": name,
            "killed": killed,
            "exit_code": output.returncode,
            "summary": output.stdout.strip().splitlines()[-1]
            if output.stdout
            else output.stderr[-400:],
        }
    )
print(json.dumps(results, indent=2))
assert all(x["killed"] for x in results), str(base)
