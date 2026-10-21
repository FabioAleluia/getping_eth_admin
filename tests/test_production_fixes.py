"""Regressões dos bloqueadores de código da avaliação de produção."""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from getping_admin.database.db import get_db
from getping_admin.database.diagnostics import schema_issues
from getping_admin.database.migrate import init_db
from tests.support import IsolatedDatabaseTestCase


class ProductionFixTests(IsolatedDatabaseTestCase):
    def user(self, username, email):
        with get_db() as conn:
            return conn.execute(
                """INSERT INTO admin_usuarios
                (nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                VALUES ('Fixture',?,?,(SELECT senha_hash FROM admin_usuarios WHERE id=1),
                        'assistente',1,0,'2026-01-01')""",
                (username, email),
            ).lastrowid

    def license(self, agents=0):
        with get_db() as conn:
            cid = conn.execute(
                "INSERT INTO clientes(nome_empresa,responsavel_nome,criado_em) "
                "VALUES ('Fixture','Responsável','2026-01-01')"
            ).lastrowid
            return conn.execute(
                """INSERT INTO licencas
                (cliente_id,chave_licenca,limite_agentes,data_emissao,data_expiracao)
                VALUES (?,'FIXTURE-KEY',?,'2026-01-01 00:00:00','2099-01-01 23:59:59')""",
                (cid, agents),
            ).lastrowid

    def post(self, path, **fields):
        return self.client.post(path, data={"csrf_token": "test-csrf", **fields})

    def production(self):
        self.app.config.update(
            ENVIRONMENT="production",
            SESSION_COOKIE_SECURE=True,
            REQUIRE_HTTPS=True,
            PUBLIC_BASE_URL="https://fixture.invalid",
            REQUIRE_FINGERPRINT=True,
        )

    def downgrade_identity(self):
        # Recria a situação pré-003 sem tocar dados operacionais.
        with get_db() as conn:
            conn.execute("DROP TRIGGER admin_identity_insert")
            conn.execute("DROP TRIGGER admin_identity_update")
            conn.execute("DROP INDEX idx_users_username_identity")
            conn.execute("DROP INDEX idx_users_email_identity")
            conn.execute("DELETE FROM schema_migrations WHERE version=3")

    def test_zero_agents_survives_render_and_save(self):
        lid = self.license()
        self.authenticate(1)
        html = self.client.get(f"/licencas/{lid}/editar").get_data(as_text=True)
        agents = re.search(r'name="limite_agentes"[^>]+value="([^"]+)"', html).group(1)
        self.assertEqual(agents, "0")
        response = self.post(
            f"/licencas/{lid}/editar",
            limite_agentes=agents,
            observacoes="Alteração sem ampliar agentes",
        )
        self.assertEqual(response.status_code, 302)
        with get_db() as conn:
            row = conn.execute("SELECT limite_agentes,observacoes FROM licencas").fetchone()
            self.assertEqual(tuple(row), (0, "Alteração sem ampliar agentes"))

    def test_missing_customer_returns_404_without_audit(self):
        self.authenticate(1)
        self.assertEqual(self.post("/clientes/999999/excluir").status_code, 404)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM admin_audit").fetchone()[0], 0)

    def test_database_rejects_cross_identity_collisions_on_insert_and_update(self):
        uid = self.user("user@example.com", "other@example.com")
        for username, email in (
            (" ADMINISTRATOR@GETPING.LOCAL ", "new@example.com"),
            ("another", " USER@EXAMPLE.COM "),
            (" ADMINISTRATOR ", "new@example.com"),
            ("another", " ADMINISTRATOR@GETPING.LOCAL "),
        ):
            with self.subTest(username=username, email=email):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.user(username, email)
        with self.assertRaises(sqlite3.IntegrityError), get_db() as conn:
            conn.execute("UPDATE admin_usuarios SET email=' ADMINISTRATOR ' WHERE id=?", (uid,))

    def test_concurrent_cross_namespace_claim_has_one_winner(self):
        barrier = Barrier(2)

        def claim(username, email):
            with self.app.app_context():
                barrier.wait(timeout=5)
                try:
                    self.user(username, email)
                    return True
                except sqlite3.IntegrityError:
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(claim, "shared@example.com", "first@example.com"),
                pool.submit(claim, "second", "shared@example.com"),
            ]
            self.assertEqual(sorted(task.result() for task in attempts), [False, True])

    def test_creation_normalizes_and_rejects_cross_namespace_collision(self):
        self.authenticate(1)
        response = self.post(
            "/usuarios/novo",
            nome="Conta",
            username="  Mixed.User  ",
            email="  MiXeD@Example.COM  ",
            papel="assistente",
            senha_inicial="Fixture@123",
        )
        self.assertEqual(response.status_code, 302)
        with get_db() as conn:
            row = conn.execute("SELECT username,email FROM admin_usuarios WHERE id!=1").fetchone()
            self.assertEqual(tuple(row), ("mixed.user", "mixed@example.com"))
        response = self.post(
            "/usuarios/novo",
            nome="Outra",
            username="MIXED@EXAMPLE.COM",
            email="unused@example.com",
            papel="assistente",
            senha_inicial="Fixture@123",
        )
        self.assertEqual(response.status_code, 200)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM admin_usuarios").fetchone()[0], 2)

    def test_login_normalizes_username_and_email(self):
        for identifier in ("  AdMiNiStRaToR  ", "  ADMINISTRATOR@GETPING.LOCAL  "):
            with self.subTest(identifier=identifier):
                client = self.app.test_client()
                client.get("/login")
                with client.session_transaction() as sess:
                    token = sess["_csrf_token"]
                response = client.post(
                    "/login",
                    data={
                        "username": identifier,
                        "senha": "SenhaForte@123",
                        "csrf_token": token,
                    },
                )
                self.assertEqual(response.status_code, 302)
                with client.session_transaction() as sess:
                    self.assertEqual(sess["user_id"], 1)

    def test_ambiguous_legacy_login_never_selects_a_matching_password(self):
        self.downgrade_identity()
        self.user("administrator@getping.local", "other@example.com")
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            token = sess["_csrf_token"]
        response = self.client.post(
            "/login",
            data={
                "username": "administrator@getping.local",
                "senha": "SenhaForte@123",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    def test_profile_normalizes_and_rejects_email_matching_another_username(self):
        self.user("reserved@example.com", "contact@example.com")
        self.authenticate(1)
        self.assertEqual(
            self.post(
                "/perfil",
                nome="Admin",
                email=" RESERVED@EXAMPLE.COM ",
            ).status_code,
            200,
        )
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT email FROM admin_usuarios WHERE id=1").fetchone()[0],
                "administrator@getping.local",
            )
        self.assertEqual(
            self.post(
                "/perfil",
                nome="Admin",
                email=" NEW@EXAMPLE.COM ",
            ).status_code,
            302,
        )
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT email FROM admin_usuarios WHERE id=1").fetchone()[0],
                "new@example.com",
            )

    def test_admin_edit_rejects_email_matching_another_username(self):
        self.user("reserved@example.com", "contact@example.com")
        uid = self.user("editable", "editable@example.com")
        self.authenticate(1)
        response = self.post(
            f"/usuarios/{uid}/editar",
            nome="Edited",
            email="RESERVED@EXAMPLE.COM",
            papel="assistente",
            ativo="1",
        )
        self.assertEqual(response.status_code, 200)
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT email FROM admin_usuarios WHERE id=?", (uid,)).fetchone()[0],
                "editable@example.com",
            )

    def test_cli_reset_normalizes_username(self):
        result = self.app.test_cli_runner().invoke(
            args=[
                "reset-password",
                " ADMINISTRATOR ",
                "--password",
                "NewPassword@123",
            ]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT auth_version FROM admin_usuarios").fetchone()[0], 1
            )

    def test_cli_create_admin_validates_email_and_cross_identity(self):
        with get_db() as conn:
            conn.execute("DELETE FROM admin_usuarios")
            conn.execute(
                "INSERT INTO admin_usuarios(nome,username,email,senha_hash,papel,criado_em) "
                "VALUES ('Fixture','reserved@example.com','contact@example.com','x','assistente','2026-01-01')"
            )
        runner = self.app.test_cli_runner()
        for email in ("invalid@", "RESERVED@EXAMPLE.COM"):
            result = runner.invoke(
                args=["create-admin", "--email", email, "--password", "NewPassword@123"]
            )
            self.assertNotEqual(result.exit_code, 0)
        result = runner.invoke(
            args=["create-admin", "--email", " ADMIN@EXAMPLE.COM ", "--password", "NewPassword@123"]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        with get_db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT email FROM admin_usuarios WHERE papel='superadmin'"
                ).fetchone()[0],
                "admin@example.com",
            )

    def test_database_rejects_invalid_license_storage_on_insert_and_update(self):
        lid = self.license()
        for column in ("limite_hosts", "limite_agentes"):
            for value in ("invalid", 1.5, None, -1, 10001):
                with self.subTest(column=column, value=value):
                    with self.assertRaises(sqlite3.IntegrityError), get_db() as conn:
                        conn.execute(f"UPDATE licencas SET {column}=? WHERE id=?", (value, lid))
                    with self.assertRaises(sqlite3.IntegrityError), get_db() as conn:
                        conn.execute(
                            f"INSERT INTO licencas(cliente_id,chave_licenca,{column},data_emissao,data_expiracao) "
                            "VALUES (1,'SECOND',?,'2026-01-01 00:00:00','2099-01-01 23:59:59')",
                            (value,),
                        )
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT limite_agentes FROM licencas").fetchone()[0], 0)

    def test_legacy_invalid_limits_return_json_503_and_are_reported(self):
        lid = self.license()
        with get_db() as conn:
            conn.execute("DROP TRIGGER licencas_validate_update")
        for value in ("invalid", 1.5, -1):
            with self.subTest(value=value):
                with get_db() as conn:
                    conn.execute("UPDATE licencas SET limite_hosts=? WHERE id=?", (value, lid))
                response = self.client.post(
                    "/api/v1/licenca/validar", json={"chave_licenca": "FIXTURE-KEY"}
                )
                self.assertEqual(response.status_code, 503)
                self.assertFalse(response.json["valido"])
                result = self.app.test_cli_runner().invoke(args=["check-data"])
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("Licenças inválidas", result.output)

    def test_migration_normalizes_accounts_preserving_password_and_auth_version(self):
        self.downgrade_identity()
        with get_db() as conn:
            conn.execute(
                "UPDATE admin_usuarios SET username=' AdMiNiStRaToR ',email=' ADMIN@EXAMPLE.COM ',auth_version=7"
            )
            before = conn.execute("SELECT senha_hash FROM admin_usuarios").fetchone()[0]
        init_db()
        init_db()
        with get_db() as conn:
            row = conn.execute(
                "SELECT username,email,senha_hash,auth_version FROM admin_usuarios"
            ).fetchone()
            self.assertEqual(tuple(row), ("administrator", "admin@example.com", before, 7))
            self.assertEqual(schema_issues(conn), [])

    def test_migration_refuses_conflicts_without_partial_normalization(self):
        self.downgrade_identity()
        self.user("administrator@getping.local", "other@example.com")
        with get_db() as conn:
            conn.execute("UPDATE admin_usuarios SET username=' AdMiNiStRaToR ' WHERE id=1")
        with self.assertRaisesRegex(RuntimeError, "IDs"):
            init_db()
        result = self.app.test_cli_runner().invoke(args=["init-db"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("IDs", result.output)
        self.assertNotIn("administrator@getping.local", result.output)
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT username FROM admin_usuarios WHERE id=1").fetchone()[0],
                " AdMiNiStRaToR ",
            )
            self.assertIsNone(
                conn.execute("SELECT version FROM schema_migrations WHERE version=3").fetchone()
            )
        self.assertNotEqual(self.app.test_cli_runner().invoke(args=["check-data"]).exit_code, 0)

    def test_migration_preserves_inconsistent_commercial_data_for_review(self):
        self.license()
        self.downgrade_identity()
        with get_db() as conn:
            conn.execute("DROP TRIGGER licencas_validate_update")
            conn.execute("UPDATE licencas SET limite_hosts='invalid'")
            # A migração anterior existente tinha trigger de faixa, não de tipo.
            conn.execute(
                "CREATE TRIGGER licencas_validate_update BEFORE UPDATE ON licencas BEGIN SELECT 1; END"
            )
        init_db()
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT limite_hosts FROM licencas").fetchone()[0], "invalid"
            )
        self.assertNotEqual(self.app.test_cli_runner().invoke(args=["check-data"]).exit_code, 0)

    def test_deep_check_detects_data_even_when_structure_is_complete(self):
        self.license()
        self.downgrade_identity()
        with get_db() as conn:
            conn.execute("DROP TRIGGER licencas_validate_update")
            conn.execute("UPDATE licencas SET limite_hosts=-1")
            conn.execute(
                "CREATE TRIGGER licencas_validate_update BEFORE UPDATE ON licencas BEGIN SELECT 1; END"
            )
        init_db()
        self.production()
        for args in (["security-check"], ["security-check", "--strict"]):
            result = self.app.test_cli_runner().invoke(args=args)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Licenças inválidas", result.output)
        # Health é readiness de estrutura; não faz scan comercial a cada chamada.
        self.assertEqual(
            self.client.get("/health", base_url="https://fixture.invalid").status_code, 200
        )

    def test_missing_or_modified_schema_objects_fail_readiness_and_diagnostics(self):
        self.production()
        self.assertEqual(
            self.app.test_cli_runner().invoke(args=["security-check", "--strict"]).exit_code, 0
        )
        for sql in (
            "DROP TRIGGER licencas_validate_update",
            "CREATE TRIGGER licencas_validate_update BEFORE UPDATE ON licencas BEGIN SELECT 1; END",
            "DROP INDEX idx_users_username_identity",
        ):
            with self.subTest(sql=sql):
                with get_db() as conn:
                    conn.execute(sql)
                result = self.app.test_cli_runner().invoke(args=["security-check", "--strict"])
                self.assertNotEqual(result.exit_code, 0)
                self.assertEqual(
                    self.client.get("/health", base_url="https://fixture.invalid").status_code, 503
                )
        # init-db não deve mascarar drift em uma migração já registrada.
        init_db()
        with get_db() as conn:
            self.assertTrue(schema_issues(conn))

    def test_missing_required_column_fails_readiness_and_deep_check(self):
        with get_db() as conn:
            conn.execute("ALTER TABLE clientes DROP COLUMN telefone")
        self.assertEqual(self.client.get("/health").status_code, 503)
        result = self.app.test_cli_runner().invoke(args=["security-check"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Colunas obrigatórias ausentes", result.output)

    def test_migration_refuses_empty_identity_and_reports_only_ids(self):
        self.downgrade_identity()
        with get_db() as conn:
            conn.execute("UPDATE admin_usuarios SET email='   '")
        result = self.app.test_cli_runner().invoke(args=["init-db"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("IDs", result.output)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT email FROM admin_usuarios").fetchone()[0], "   ")
            self.assertIsNone(
                conn.execute("SELECT version FROM schema_migrations WHERE version=3").fetchone()
            )
