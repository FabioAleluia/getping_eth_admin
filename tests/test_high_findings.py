import sqlite3
from pathlib import Path
from time import time

from getping_admin import create_app
from getping_admin.database.db import get_db
from getping_admin.database.migrate import init_db
from tests.support import IsolatedDatabaseTestCase


class HighFindingsTests(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO clientes(id,nome_empresa,responsavel_nome,criado_em) VALUES(1,'Test','Resp','2026-01-01')"
            )
            conn.execute("""INSERT INTO licencas(id,cliente_id,chave_licenca,status,data_emissao,data_expiracao)
                VALUES(1,1,'K','ativa','2026-01-01','2099-12-31 23:59:59')""")

    def validate(self, fp=None, client=None, **kwargs):
        payload = {"chave_licenca": "K"}
        if fp is not None:
            payload["fingerprint"] = fp
        return (client or self.client).post("/api/v1/licenca/validar", json=payload, **kwargs)

    def authorize(self, fp="LEGIT", **extra):
        return self.client.post(
            "/licencas/1/vincular-instancia",
            data={
                "fingerprint": fp,
                "senha_atual": "SenhaForte@123",
                "csrf_token": "test-csrf",
                **extra,
            },
        )

    def test_quoted_equivalent_schema_keeps_revoked_cookie_invalid(self):
        path = Path(self.tempdir.name) / "quoted.db"
        schema = (
            Path("getping_admin/database/schema.sql")
            .read_text()
            .replace("'assistente'", '"assistente"')
        )
        with sqlite3.connect(path) as conn:
            conn.executescript(schema)
            conn.execute("""INSERT INTO admin_usuarios(id,nome,username,email,senha_hash,papel,ativo,trocar_senha,auth_version,criado_em)
                VALUES(1,'Admin','administrator','a@example.com','hash','superadmin',1,0,7,'2026-01-01')""")
        self.app.config["DATABASE"] = str(path)
        cookie = self.app.session_interface.get_signing_serializer(self.app).dumps(
            {"user_id": 1, "auth_version": 0, "issued_at": time(), "last_seen": time()}
        )
        init_db()
        init_db()
        self.client.set_cookie("session", cookie)
        self.assertIn("/login", self.client.get("/usuarios/").location)
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT auth_version FROM admin_usuarios").fetchone()[0], 7
            )

    def test_real_legacy_rebuild_preserves_version_indexes_triggers_and_sequence(self):
        path = Path(self.tempdir.name) / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.executescript("""CREATE TABLE admin_usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,senha_hash TEXT NOT NULL,
                papel TEXT NOT NULL CHECK(papel IN ('superadmin','gestor')),ativo INTEGER NOT NULL DEFAULT 1,
                trocar_senha INTEGER NOT NULL DEFAULT 1,criado_em TEXT NOT NULL,ultimo_login TEXT,
                auth_version INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX custom_admin_name ON admin_usuarios(nome);
                CREATE TABLE touches(id INTEGER);
                CREATE TRIGGER custom_admin_touch AFTER UPDATE ON admin_usuarios
                BEGIN INSERT INTO touches VALUES(NEW.id); END;
                INSERT INTO admin_usuarios VALUES(1,'A','administrator','a@example.com','hash','superadmin',1,0,'2026-01-01',NULL,7);
                INSERT INTO admin_usuarios VALUES(99,'B','deleted','b@example.com','hash','gestor',1,0,'2026-01-01',NULL,3);
                DELETE FROM admin_usuarios WHERE id=99;
            """)
        self.app.config["DATABASE"] = str(path)
        init_db()
        with get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT auth_version FROM admin_usuarios").fetchone()[0], 7
            )
            self.assertEqual(
                conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='admin_usuarios'"
                ).fetchone()[0],
                99,
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='custom_admin_name'"
                ).fetchone()
            )
            conn.execute("UPDATE admin_usuarios SET nome='Updated' WHERE id=1")
            self.assertEqual(conn.execute("SELECT id FROM touches").fetchone()[0], 1)

    def test_csrf_less_distributed_requests_do_not_lock_victim(self):
        self.app.config["LOGIN_RATE_LIMIT"] = 2
        for ip in ("192.0.2.1", "192.0.2.2", "192.0.2.3", "192.0.2.4"):
            attacker = self.app.test_client()
            for _ in range(2):
                self.assertEqual(
                    attacker.post(
                        "/login",
                        data={"username": "administrator"},
                        environ_overrides={"REMOTE_ADDR": ip},
                    ).status_code,
                    400,
                )
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            token = sess["_csrf_token"]
        response = self.client.post(
            "/login",
            data={"username": "administrator", "senha": "SenhaForte@123", "csrf_token": token},
            environ_overrides={"REMOTE_ADDR": "192.0.2.5"},
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["user_id"], 1)

    def test_valid_csrf_wrong_password_does_not_globally_lock_victim(self):
        self.app.config["LOGIN_RATE_LIMIT"] = 1
        for i in range(4):
            attacker = self.app.test_client()
            attacker.get("/login")
            with attacker.session_transaction() as sess:
                token = sess["_csrf_token"]
            attacker.post(
                "/login",
                data={"username": "administrator", "senha": "Wrong@123", "csrf_token": token},
                environ_overrides={"REMOTE_ADDR": f"192.0.2.{i + 1}"},
            )
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            token = sess["_csrf_token"]
        self.assertEqual(
            self.client.post(
                "/login",
                data={"username": "administrator", "senha": "SenhaForte@123", "csrf_token": token},
                environ_overrides={"REMOTE_ADDR": "192.0.2.99"},
            ).status_code,
            302,
        )

    def test_unknown_installation_cannot_claim_strict_license(self):
        self.app.config["REQUIRE_FINGERPRINT"] = True
        self.assertEqual(self.validate("ATTACKER").status_code, 403)
        self.assertEqual(self.validate("LEGIT").status_code, 403)
        self.assertEqual(self.validate().status_code, 400)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM license_bindings").fetchone()[0], 0)

    def test_old_observed_fingerprint_is_not_an_authorized_binding(self):
        self.app.config["REQUIRE_FINGERPRINT"] = True
        with get_db() as conn:
            conn.execute("UPDATE licencas SET instancia_fingerprint='OLD'")
        self.assertEqual(self.validate("OLD").status_code, 403)

    def test_gradual_authorization_enforces_even_in_compatibility_mode(self):
        self.assertEqual(self.validate().status_code, 200)
        self.authenticate(1)
        self.assertEqual(self.authorize().status_code, 302)
        self.assertEqual(self.validate("LEGIT").status_code, 200)
        self.assertEqual(self.validate("OTHER").status_code, 403)
        self.assertEqual(self.validate().status_code, 400)
        with get_db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT actor_id FROM admin_audit WHERE action='authorize_instance'"
                ).fetchone()[0],
                1,
            )

    def test_binding_requires_current_password_and_csrf(self):
        self.authenticate(1)
        self.assertEqual(self.authorize(senha_atual="wrong").status_code, 403)
        self.assertEqual(self.authorize(csrf_token="wrong").status_code, 400)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM license_bindings").fetchone()[0], 0)

    def test_binding_release_does_not_allow_first_caller_to_steal_license(self):
        self.authenticate(1)
        self.authorize()
        self.client.post("/licencas/1/liberar-instancia", data={"csrf_token": "test-csrf"})
        self.assertEqual(self.validate("ATTACKER").status_code, 403)
        self.assertEqual(self.validate("LEGIT").status_code, 403)
        self.assertEqual(self.authorize("NEW").status_code, 302)
        self.assertEqual(self.validate("NEW").status_code, 200)
        self.assertEqual(self.validate("LEGIT").status_code, 403)

    def test_https_rejects_http_api_without_claiming_or_checkin(self):
        self.app.config.update(REQUIRE_HTTPS=True, PUBLIC_BASE_URL="https://admin.example.test")
        response = self.validate("ATTACKER")
        self.assertEqual(response.status_code, 426)
        self.assertFalse(response.json["valido"])
        self.assertEqual(
            self.validate("LEGIT", base_url="https://admin.example.test").status_code, 200
        )

    def test_https_redirect_uses_configured_origin_not_host_header(self):
        self.app.config.update(REQUIRE_HTTPS=True, PUBLIC_BASE_URL="https://admin.example.test")
        response = self.client.get(
            "/login?next=/clientes/", headers={"Host": "attacker.example.test"}
        )
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.location, "https://admin.example.test/login?next=/clientes/")
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_https_configuration_rejects_insecure_origin_and_cookies(self):
        for origin in (
            "http://admin.test",
            "https://user:pass@admin.test",
            "https://admin.test/path",
        ):
            with self.assertRaises(RuntimeError):
                create_app(
                    {
                        "SECRET_KEY": self.app.secret_key,
                        "REQUIRE_HTTPS": True,
                        "PUBLIC_BASE_URL": origin,
                    }
                )
        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "SECRET_KEY": self.app.secret_key,
                    "REQUIRE_HTTPS": True,
                    "PUBLIC_BASE_URL": "https://admin.test",
                    "SESSION_COOKIE_SECURE": False,
                }
            )

    def test_new_licenses_require_explicit_authorization_by_default(self):
        self.authenticate(1)
        response = self.client.post(
            "/licencas/nova", data={"cliente_id": 1, "csrf_token": "test-csrf"}
        )
        self.assertEqual(response.status_code, 302)
        with get_db() as conn:
            new = conn.execute(
                "SELECT id,chave_licenca FROM licencas ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNone(
                conn.execute(
                    "SELECT fingerprint FROM license_bindings WHERE licenca_id=?", (new["id"],)
                ).fetchone()[0]
            )
        response = self.client.post(
            "/api/v1/licenca/validar",
            json={"chave_licenca": new["chave_licenca"], "fingerprint": "FIRST"},
        )
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_authorize_a_fingerprint(self):
        with get_db() as conn:
            conn.execute("""INSERT INTO admin_usuarios(nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                VALUES('M','manager','m@example.com','hash','gestor',1,0,'2026-01-01')""")
            uid = conn.execute("SELECT id FROM admin_usuarios WHERE username='manager'").fetchone()[
                0
            ]
        self.authenticate(uid)
        self.assertEqual(self.authorize().status_code, 403)

    def test_https_works_behind_explicitly_trusted_proxy(self):
        proxy_app = create_app(
            {
                "SECRET_KEY": self.app.secret_key,
                "TESTING": True,
                "DATABASE": self.app.config["DATABASE"],
                "REQUIRE_HTTPS": True,
                "PUBLIC_BASE_URL": "https://admin.example.test",
                "SESSION_COOKIE_SECURE": True,
                "TRUSTED_PROXY_HOPS": 1,
                "LOGIN_RATE_LIMIT": 0,
                "API_RATE_LIMIT": 0,
            }
        )
        response = proxy_app.test_client().post(
            "/api/v1/licenca/validar",
            json={"chave_licenca": "K"},
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "192.0.2.1"},
        )
        self.assertEqual(response.status_code, 200)

    def test_https_does_not_trust_forwarded_proto_without_proxy_configuration(self):
        self.app.config.update(REQUIRE_HTTPS=True, PUBLIC_BASE_URL="https://admin.example.test")
        self.assertEqual(self.validate(headers={"X-Forwarded-Proto": "https"}).status_code, 426)
