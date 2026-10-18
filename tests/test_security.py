import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask

from getping_admin import create_app
from getping_admin.database.db import get_db
from getping_admin.database.migrate import init_db
from tests.support import IsolatedDatabaseTestCase


class SecurityRegressionTests(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with get_db() as conn:
            for uid, role in [(2, "gestor"), (3, "assistente")]:
                conn.execute(
                    """INSERT INTO admin_usuarios
                    (id,nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                    VALUES (?,?,?,?,?,?,1,0,'2026-01-01 00:00:00')""",
                    (uid, role, role, role + "@example.com", "unused", role),
                )
            conn.execute(
                "INSERT INTO clientes(id,nome_empresa,responsavel_nome,ativo,criado_em) VALUES(1,'Teste','Resp',1,'2026-01-01 00:00:00')"
            )
            conn.execute("""INSERT INTO licencas
                (id,cliente_id,chave_licenca,tipo_plano,limite_hosts,limite_agentes,status,data_emissao,data_expiracao)
                VALUES(1,1,'TEST-KEY','Basico',10,5,'ativa','2026-01-01 00:00:00','2099-12-31 23:59:59')""")

    def post(self, path, data=None):
        return self.client.post(path, data=dict(data or {}, csrf_token="test-csrf"))

    def validate(self, **kwargs):
        return self.client.post(
            "/api/v1/licenca/validar", json=dict(chave_licenca="TEST-KEY", **kwargs)
        )

    def test_secret_required_and_known_secret_rejected(self):
        for secret in (None, "", "short", "getping-admin-super-secret-key-change-in-production"):
            with self.subTest(secret=bool(secret)), self.assertRaises(RuntimeError):
                create_app({"SECRET_KEY": secret})

    def test_testing_rejects_operational_database(self):
        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": secrets.token_hex(32),
                    "DATABASE": str(Path.cwd() / "database/db_getping.db"),
                }
            )

    def test_old_secret_cannot_forge_cookie(self):
        fake = Flask("forger")
        fake.secret_key = "getping-admin-super-secret-key-change-in-production"
        cookie = fake.session_interface.get_signing_serializer(fake).dumps(
            {"user_id": 1, "auth_version": 0}
        )
        self.client.set_cookie("session", cookie)
        response = self.client.get("/usuarios/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_gestor_cannot_promote_self_or_assistant(self):
        self.authenticate(2)
        for uid, role in [(2, "superadmin"), (3, "superadmin"), (3, "gestor")]:
            response = self.post(
                f"/usuarios/{uid}/editar",
                {"nome": "X", "email": f"x{uid}@example.com", "papel": role, "ativo": "1"},
            )
            self.assertEqual(response.status_code, 403)
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT papel FROM admin_usuarios WHERE id=2").fetchone()[0], "gestor"
            )
            self.assertEqual(
                conn.execute("SELECT papel FROM admin_usuarios WHERE id=3").fetchone()[0],
                "assistente",
            )

    def test_deleted_and_inactive_sessions_cannot_write(self):
        for mode in ("deleted", "inactive"):
            self.authenticate(3)
            with get_db() as conn:
                if mode == "deleted":
                    conn.execute("DELETE FROM admin_usuarios WHERE id=3")
                else:
                    conn.execute("UPDATE admin_usuarios SET ativo=0 WHERE id=3")
            response = self.post("/licencas/nova", {"cliente_id": 1, "dias_validade": 30})
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login", response.location)
            with get_db() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)
                if mode == "deleted":
                    conn.execute(
                        "INSERT INTO admin_usuarios(id,nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em) VALUES(3,'A','a','a@a.com','x','assistente',1,0,'2026-01-01')"
                    )

    def test_password_change_revokes_second_session(self):
        self.authenticate(1)
        other = self.authenticate(1, self.app.test_client())
        response = self.post(
            "/perfil",
            {
                "nome": "Admin",
                "email": "admin@example.com",
                "senha_atual": "SenhaForte@123",
                "nova_senha": "Changed@123",
                "confirma_senha": "Changed@123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.get("/usuarios/").status_code, 302)
        self.assertEqual(self.client.get("/usuarios/").status_code, 200)

    def test_password_reset_revokes_existing_session(self):
        other = self.authenticate(3, self.app.test_client())
        self.authenticate(1)
        response = self.post(
            "/usuarios/3/editar",
            {
                "nome": "Assistente",
                "email": "assistente@example.com",
                "papel": "assistente",
                "ativo": "1",
                "nova_senha": "Reset@123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.get("/clientes/").status_code, 302)

    def test_assistant_commercial_changes_denied_by_default(self):
        self.authenticate(3)
        self.assertEqual(
            self.post("/licencas/1/editar", {"tipo_plano": "Enterprise"}).status_code, 403
        )
        self.assertEqual(
            self.post("/licencas/1/status", {"novo_status": "cancelada"}).status_code, 403
        )
        html = self.client.get("/licencas/").data
        self.assertNotIn(b'href="/licencas/1/editar"', html)

    def test_strict_fingerprint_required_and_checked(self):
        self.app.config["REQUIRE_FINGERPRINT"] = True
        self.assertEqual(self.validate().status_code, 400)
        self.assertEqual(self.validate(fingerprint="A").status_code, 200)
        self.assertEqual(self.validate(fingerprint="B").status_code, 403)
        self.assertEqual(self.validate(fingerprint="A").status_code, 200)

    def test_compatibility_mode_keeps_legacy_clients(self):
        self.assertEqual(self.validate().status_code, 200)
        self.assertEqual(self.validate(fingerprint="A").status_code, 200)
        self.assertEqual(self.validate(fingerprint="B").status_code, 200)

    def test_first_activation_is_atomic(self):
        self.app.config["REQUIRE_FINGERPRINT"] = True

        def activate(fp):
            with self.app.test_client() as client:
                return client.post(
                    "/api/v1/licenca/validar", json={"chave_licenca": "TEST-KEY", "fingerprint": fp}
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(activate, ["A", "B"])), [200, 403])

    def test_instance_release_requires_superadmin_and_is_audited(self):
        self.app.config["REQUIRE_FINGERPRINT"] = True
        self.validate(fingerprint="A")
        self.authenticate(2)
        self.assertEqual(self.post("/licencas/1/liberar-instancia").status_code, 403)
        self.authenticate(1)
        self.assertEqual(self.post("/licencas/1/liberar-instancia").status_code, 302)
        self.assertEqual(self.validate(fingerprint="B").status_code, 200)
        with get_db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT actor_id FROM admin_audit WHERE action='release_instance'"
                ).fetchone()[0],
                1,
            )

    def test_bad_json_and_payloads_return_json_errors(self):
        for payload in (
            None,
            [],
            [1],
            True,
            {"chave_licenca": None},
            {"chave_licenca": 123},
            {"chave_licenca": "x" * 129},
            {"chave_licenca": "TEST-KEY", "fingerprint": []},
            {"chave_licenca": "TEST-KEY", "versao": 42},
        ):
            response = self.client.post("/api/v1/licenca/validar", json=payload)
            self.assertEqual(response.status_code, 400, repr(payload))
            self.assertFalse(response.json["valido"])
        response = self.client.post(
            "/api/v1/licenca/validar", data="x" * 40000, content_type="application/json"
        )
        self.assertEqual(response.status_code, 413)
        self.assertFalse(response.json["valido"])

    def test_invalid_license_fields_do_not_change_database(self):
        self.authenticate(1)
        for fields in (
            {"data_expiracao": "garbage"},
            {"data_expiracao": "2026-02-31"},
            {"limite_hosts": "-1"},
            {"limite_agentes": "-1"},
            {"limite_hosts": "abc"},
            {"limite_hosts": "10001"},
            {"status": "wrong"},
            {"tipo_plano": "Wrong"},
        ):
            response = self.post("/licencas/1/editar", fields)
            self.assertEqual(response.status_code, 400, str(fields))
        with get_db() as conn:
            row = conn.execute("SELECT * FROM licencas WHERE id=1").fetchone()
            self.assertEqual(row["data_expiracao"], "2099-12-31 23:59:59")
            self.assertEqual(row["limite_hosts"], 10)

    def test_issuance_requires_active_existing_customer(self):
        self.authenticate(1)
        with get_db() as conn:
            conn.execute("UPDATE clientes SET ativo=0 WHERE id=1")
        for cid in (1, 999):
            self.post("/licencas/nova", {"cliente_id": cid})
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)

    def test_database_rejects_negative_limits(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with get_db() as conn:
                conn.execute("UPDATE licencas SET limite_hosts=-1 WHERE id=1")

    def test_administrative_audit_contains_actor_changes_no_password(self):
        self.authenticate(1)
        self.post(
            "/usuarios/3/editar",
            {
                "nome": "New Name",
                "email": "new@example.com",
                "papel": "assistente",
                "ativo": "1",
                "nova_senha": "NeverLog@123",
            },
        )
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM admin_audit WHERE entity='usuario' AND action='update'"
            ).fetchone()
            self.assertEqual(row["actor_id"], 1)
            self.assertIn("New Name", row["after_json"])
            self.assertNotIn("NeverLog", row["after_json"])
            self.assertNotIn("senha_hash", row["before_json"])

    def test_proxy_header_not_trusted_by_default_and_logs_aggregated(self):
        for _ in range(3):
            self.client.post(
                "/api/v1/licenca/validar",
                json={"chave_licenca": "TEST-KEY"},
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
        for _ in range(3):
            self.client.post("/api/v1/licenca/validar", json={"chave_licenca": "unknown"})
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM licenca_logs").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ip_origem"], "127.0.0.1")
            self.assertNotEqual(rows[0]["chave_usada"], "TEST-KEY")

    def test_rate_limit_shared_across_clients(self):
        self.app.config["API_RATE_LIMIT"] = 2
        self.assertEqual(self.validate().status_code, 200)
        other = self.app.test_client()
        self.assertEqual(
            other.post("/api/v1/licenca/validar", json={"chave_licenca": "TEST-KEY"}).status_code,
            200,
        )
        response = self.validate()
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertFalse(response.json["valido"])

    def test_login_rate_limit(self):
        self.app.config["LOGIN_RATE_LIMIT"] = 2
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            token = sess["_csrf_token"]
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    "/login", data={"username": "nobody", "senha": "invalid", "csrf_token": token}
                ).status_code,
                200,
            )
        self.assertEqual(
            self.client.post(
                "/login", data={"username": "nobody", "senha": "invalid", "csrf_token": token}
            ).status_code,
            429,
        )

    def test_api_ignores_panel_first_access_session(self):
        self.authenticate(1)
        with get_db() as conn:
            conn.execute("UPDATE admin_usuarios SET trocar_senha=1 WHERE id=1")
        self.assertEqual(self.validate().status_code, 200)

    def test_dashboard_and_listing_use_effective_status(self):
        self.authenticate(1)
        with get_db() as conn:
            conn.execute("UPDATE licencas SET data_expiracao='2020-01-01 00:00:00'")
        self.assertEqual(self.validate().status_code, 403)
        self.assertNotIn(b"TEST-KEY", self.client.get("/licencas/?status=ativa").data)
        self.assertIn(b"TEST-KEY", self.client.get("/licencas/?status=expirada").data)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_pagination_does_not_load_all_customers(self):
        self.authenticate(1)
        with get_db() as conn:
            for i in range(60):
                conn.execute(
                    "INSERT INTO clientes(nome_empresa,responsavel_nome,criado_em) VALUES(?, 'R','2026-01-01')",
                    (f"Customer{i:03}",),
                )
        first = self.client.get("/clientes/")
        second = self.client.get("/clientes/?pagina=2")
        self.assertIn(b"Customer000", first.data)
        self.assertNotIn(b"Customer059", first.data)
        self.assertIn(b"Customer059", second.data)
        self.assertIn(b"pagina=2", first.data)

    def test_security_headers_and_logout_csrf(self):
        self.authenticate(1)
        response = self.client.get("/usuarios/")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertEqual(self.post("/logout").status_code, 302)

    def test_migrations_idempotent_and_do_not_reset_admin(self):
        with get_db() as conn:
            before = conn.execute("SELECT senha_hash FROM admin_usuarios WHERE id=1").fetchone()[0]
        init_db()
        init_db()
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT senha_hash FROM admin_usuarios WHERE id=1").fetchone()[0],
                before,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1
            )

    def test_cli_backup_restore_and_no_overwrite(self):
        destination = Path(self.tempdir.name) / "backup.db"
        result = self.app.test_cli_runner().invoke(args=["backup-db", str(destination)])
        self.assertEqual(result.exit_code, 0, result.output)
        with sqlite3.connect(destination) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM licencas").fetchone()[0], 1)
        self.assertNotEqual(
            self.app.test_cli_runner().invoke(args=["backup-db", str(destination)]).exit_code, 0
        )

    def test_cli_provisioning_never_automatically_recreates_admin(self):
        with get_db() as conn:
            conn.execute("DELETE FROM admin_usuarios")
        init_db()
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM admin_usuarios").fetchone()[0], 0)
        runner = self.app.test_cli_runner()
        result = runner.invoke(
            args=["create-admin", "--email", "owner@example.com", "--password", "administrator"]
        )
        self.assertNotEqual(result.exit_code, 0)
        result = runner.invoke(
            args=["create-admin", "--email", "owner@example.com", "--password", "Provisioned@123"]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotEqual(
            runner.invoke(
                args=[
                    "create-admin",
                    "--email",
                    "other@example.com",
                    "--password",
                    "Provisioned@123",
                ]
            ).exit_code,
            0,
        )

    def test_log_retention_preserves_audit(self):
        self.authenticate(1)
        self.post("/licencas/1/status", {"novo_status": "suspensa"})
        with get_db() as conn:
            conn.execute(
                "INSERT INTO licenca_logs(evento,criado_em) VALUES('old','2000-01-01 00:00:00')"
            )
        result = self.app.test_cli_runner().invoke(args=["prune-logs"])
        self.assertEqual(result.exit_code, 0, result.output)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM licenca_logs").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM admin_audit").fetchone()[0], 1)

    def test_insecure_legacy_password_rejected_and_local_recovery(self):
        from werkzeug.security import generate_password_hash

        with get_db() as conn:
            conn.execute(
                "UPDATE admin_usuarios SET senha_hash=? WHERE id=1",
                (generate_password_hash("administrator"),),
            )
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            token = sess["_csrf_token"]
        response = self.client.post(
            "/login",
            data={"username": "administrator", "senha": "administrator", "csrf_token": token},
        )
        self.assertIn("Credenciais inválidas".encode(), response.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)
        result = self.app.test_cli_runner().invoke(
            args=["reset-password", "administrator", "--password", "Recovered@123"]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        response = self.client.post(
            "/login",
            data={"username": "administrator", "senha": "Recovered@123", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").location, "/primeiro-acesso")

    def test_unexpected_query_parameters_do_not_break_pagination(self):
        self.authenticate(1)
        self.assertEqual(self.client.get("/clientes/?endpoint=wrong").status_code, 200)
        self.assertEqual(self.client.get("/licencas/?busca=" + "a" * 201).status_code, 400)

    def test_full_panel_pages_render_with_local_scripts(self):
        self.authenticate(1)
        for path in (
            "/",
            "/clientes/",
            "/clientes/novo",
            "/clientes/1/editar",
            "/licencas/",
            "/licencas/nova",
            "/licencas/1/editar",
            "/licencas/1/detalhes",
            "/usuarios/",
            "/usuarios/novo",
            "/usuarios/3/editar",
            "/perfil",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn(b"cdn.tailwindcss.com", response.data)
            self.assertNotIn(b"onclick=", response.data)
            self.assertNotIn(b"onsubmit=", response.data)
        with self.client.get("/static/css/tailwind.css") as response:
            self.assertEqual(response.status_code, 200)

    def test_unicode_csrf_is_rejected_without_internal_error(self):
        self.authenticate(1)
        self.assertEqual(
            self.client.post(
                "/licencas/1/status", data={"csrf_token": "inválido", "novo_status": "ativa"}
            ).status_code,
            400,
        )

    def test_production_cookie_requires_https(self):
        self.app.config.update(SESSION_COOKIE_SECURE=True, ENVIRONMENT="production")
        response = self.client.get("/login", base_url="https://localhost")
        cookies = response.headers.getlist("Set-Cookie")
        self.assertTrue(
            any("Secure" in c and "HttpOnly" in c and "SameSite=Lax" in c for c in cookies)
        )
        self.assertIn("Strict-Transport-Security", response.headers)

    def test_key_format_preserved_and_stronger_format_opt_in(self):
        from getping_admin.licensing import gerar_chave_licenca

        self.assertRegex(gerar_chave_licenca(), r"^GPING-(?:[A-F0-9]{4}-){3}[A-F0-9]{4}$")
        self.app.config["EXTENDED_LICENSE_KEYS"] = True
        self.assertRegex(gerar_chave_licenca(), r"^GPING-(?:[A-F0-9]{8}-){3}[A-F0-9]{8}$")
