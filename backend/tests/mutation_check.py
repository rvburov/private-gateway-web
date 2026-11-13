"""Проверка тестов мутантами в отдельных временных копиях app и alembic, без правки исходников.

Каждый мутант портит одно место кода; его тест обязан упасть на проверке (assert).
Запуск: PGWEB_TEST_DATABASE_URL=... python tests/mutation_check.py [имя мутанта ...]
"""

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
MIGRATION = "alembic/versions/2408fb4c00ae_two_factor_for_admins_device_changes.py"
cases = [
    (
        "csrf",
        "app/main.py",
        'if request.method not in {"GET", "HEAD", "OPTIONS"}:',
        "if False:",
        "test_http_security.py::test_mutations_require_csrf",
    ),
    (
        "rbac",
        "app/services/admin.py",
        'if user.role != "admin":',
        "if False:",
        "test_admin.py::test_member_cannot_administer_even_by_direct_request",
    ),
    (
        "totp_replay",
        "app/core/security/totp.py",
        "if matched is None or (last_step is not None and matched <= last_step):",
        "if matched is None:",
        "test_security.py::test_totp_has_bounded_time_window_and_rejects_replay",
    ),
    (
        "admin_transaction_lock",
        "app/services/admin.py",
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
    # 2026-11-13: 2FA только у администраторов, смена устройств, удаление, очистка, .apk
    (
        "admin_session_without_2fa",
        "app/services/auth.py",
        'return or_(User.role == "member", User.totp_enabled.is_(True))',
        'return or_(User.role == "member", User.role == "admin")',
        "test_auth.py::test_admin_without_two_factor_gets_no_session_only_setup",
    ),
    (
        "admin_routes_without_2fa",
        "app/services/admin.py",
        '    if not user.totp_enabled:\n        raise AppError(403, "setup_required")\n',
        "",
        "test_deletion.py::test_admin_routes_require_configured_two_factor",
    ),
    (
        "member_login_two_steps",
        "app/services/auth.py",
        (
            "    if not needs_two_factor(user):\n"
            "        return await new_session(db, user, request, response)\n"
            "    device ="
        ),
        "    device =",
        "test_auth.py::test_member_invitation_opens_the_account_without_two_factor",
    ),
    (
        "app_code_required",
        "app/services/devices.py",
        (
            "        if body.code is None and body.recovery_code is None:\n"
            '            raise AppError(401, "code_required")\n'
        ),
        "",
        "test_devices.py::test_admin_app_login_without_code_asks_for_it_and_spends_nothing",
    ),
    (
        "app_member_code_checked",
        "app/services/devices.py",
        "    if auth.needs_two_factor(user):\n        # Администратор",
        "    if True:\n        # Администратор",
        "test_devices.py::test_member_app_login_ignores_any_code",
    ),
    (
        "device_change_limit",
        "app/services/devices.py",
        "if known is None and await changes_used(db, user, now) >= change_limit_for(user):",
        "if False:",
        "test_devices.py::test_device_change_limit_counts_new_installations_only",
    ),
    (
        "relogin_counts_as_new",
        "app/services/devices.py",
        "new_device=known is None,",
        "new_device=True,",
        "test_devices.py::test_device_change_limit_counts_new_installations_only",
    ),
    (
        "admin_removal_counted",
        "app/services/devices.py",
        "                AppDevice.removed_by_admin.is_(False),\n",
        "",
        "test_devices.py::test_device_removed_by_admin_frees_a_device_change",
    ),
    (
        "delete_self",
        "app/services/admin.py",
        (
            "    if user.id == actor.id:\n"
            '        raise AppError(400, "self_change_forbidden")\n'
            "    await _check_last_admin(db, user)\n"
            "    await db.execute(\n"
            "        delete(AccessCode)"
        ),
        "    await _check_last_admin(db, user)\n    await db.execute(\n        delete(AccessCode)",
        "test_deletion.py::test_admin_cannot_delete_self_and_deleted_admin_leaves_others",
    ),
    (
        "delete_without_totp",
        "app/services/admin.py",
        (
            "    actor = await confirm_admin(db, request, code)\n"
            "    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())\n"
            "    if not user:\n"
            '        raise AppError(404, "not_found")\n'
            "    if user.id == actor.id:"
        ),
        (
            "    actor = await require_admin(db, request)\n"
            "    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())\n"
            "    if not user:\n"
            '        raise AppError(404, "not_found")\n'
            "    if user.id == actor.id:"
        ),
        "test_deletion.py::test_admin_deletes_a_member_with_everything_except_the_download_log",
    ),
    (
        "demotion_keeps_2fa",
        "app/services/admin.py",
        "        await auth.clear_two_factor(db, user)\n",
        "        pass\n",
        "test_deletion.py::test_demoted_admin_loses_two_factor_and_signs_in_with_password",
    ),
    (
        "password_not_verified",
        "app/services/account.py",
        "if not await passwords.verify_password_async(stored_hash, body.current_password):",
        "if False:",
        "test_account.py::test_wrong_current_password_keeps_the_session_and_is_rate_limited",
    ),
    (
        "admin_password_without_code",
        "app/services/account.py",
        "    if not auth.needs_two_factor(user):\n        return\n",
        "    return\n",
        "test_account.py::test_admin_confirms_password_change_with_two_factor",
    ),
    (
        "sign_out_keeps_others",
        "app/services/account.py",
        '    await auth.revoke_access(db, user)\n    auth.audit(db, "access.signed_out_everywhere"',
        '    auth.audit(db, "access.signed_out_everywhere"',
        "test_account.py::test_member_signs_out_everywhere_except_this_browser",
    ),
    (
        "purge_ignores_change_window",
        "app/services/retention.py",
        "            AppDevice.created_at < now - timedelta(days=settings.device_change_days),\n",
        "",
        "test_retention.py::test_purge_periods_are_configurable",
    ),
    (
        "purge_keeps_used_invites",
        "app/services/retention.py",
        "                AccessCode.used_at < ended,\n",
        "",
        "test_retention.py::test_purge_removes_only_records_that_are_no_longer_needed",
    ),
    (
        "apk_octet_stream",
        "app/services/downloads.py",
        '    ".apk": "application/vnd.android.package-archive",\n',
        "",
        "test_downloads.py::test_android_package_is_served_for_the_phone_installer",
    ),
    (
        "migration_signs_out",
        MIGRATION,
        "UPDATE users SET totp_enabled = false,",
        "UPDATE users SET auth_version = auth_version + 1, totp_enabled = false,",
        "test_migrations.py::test_upgrade_removes_member_two_factor_without_signing_anyone_out",
    ),
    (
        "migration_touches_admins",
        MIGRATION,
        "MEMBERS = \"SELECT id FROM users WHERE role = 'member'\"",
        'MEMBERS = "SELECT id FROM users"',
        "test_migrations.py::test_upgrade_removes_member_two_factor_without_signing_anyone_out",
    ),
]
only = set(sys.argv[1:])
if not os.environ.get("PGWEB_TEST_DATABASE_URL"):
    raise SystemExit("PGWEB_TEST_DATABASE_URL must point to a dedicated test database")
results = []
for name, filename, original, changed, target in cases:
    if only and name not in only:
        continue
    work = base / name
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(backend / "app", work / "app", ignore=ignore)
    shutil.copytree(backend / "alembic", work / "alembic", ignore=ignore)
    shutil.copy(backend / "alembic.ini", work / "alembic.ini")
    path = work / filename
    content = path.read_text()
    assert content.count(original) == 1, name
    path.write_text(content.replace(original, changed, 1))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(work) + os.pathsep + str(backend)
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
            "-p",
            "no:cacheprovider",
            str(backend / "tests" / target),
            "-q",
            "--tb=short",
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
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
print(json.dumps(results, indent=2, ensure_ascii=False))
assert all(x["killed"] for x in results), str(base)
