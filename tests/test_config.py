"""Regressões da configuração entre factories e da escolha do banco local."""

import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from getping_admin import create_app


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.secret = secrets.token_hex(32)
        self.tempdir = tempfile.TemporaryDirectory(prefix="getping-config-")
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        environment = patch.dict("os.environ", {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def make_app(self, **overrides):
        return create_app({"SECRET_KEY": self.secret, "ENVIRONMENT": "development", **overrides})

    def test_each_factory_reads_current_environment(self):
        with patch.dict("os.environ", {"GETPING_ENV": "development", "SECRET_KEY": self.secret}):
            first = create_app()
        second_secret = secrets.token_hex(32)
        from getping_admin.license_keys import generate

        private = self.root / "license-private.pem"
        generate(private, self.root / "license-public.pem")
        with patch.dict(
            "os.environ",
            {
                "GETPING_ENV": "production",
                "SECRET_KEY": second_secret,
                "GETPING_PUBLIC_BASE_URL": "https://central.example.com",
                "GETPING_LICENSE_SIGNING_KEY_FILE": str(private),
            },
        ):
            second = create_app()
        self.assertEqual(first.secret_key, self.secret)
        self.assertFalse(first.config["SESSION_COOKIE_SECURE"])
        self.assertEqual(second.secret_key, second_secret)
        self.assertTrue(second.config["SESSION_COOKIE_SECURE"])

    def test_cookie_security_follows_final_environment_and_explicit_override(self):
        self.assertFalse(self.make_app(ENVIRONMENT="development").config["SESSION_COOKIE_SECURE"])
        self.assertTrue(
            self.make_app(ENVIRONMENT="development", SESSION_COOKIE_SECURE=True).config[
                "SESSION_COOKIE_SECURE"
            ]
        )

    def test_invalid_proxy_configuration_fails_before_serving_requests(self):
        for value in ("invalid", "-1", "1.5", -1, True, 1.5, None):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "GETPING_PROXY_HOPS"),
            ):
                self.make_app(TRUSTED_PROXY_HOPS=value)

    def test_proxy_override_takes_precedence_over_environment(self):
        with patch.dict("os.environ", {"GETPING_PROXY_HOPS": "invalid"}):
            app = self.make_app(TRUSTED_PROXY_HOPS=0)
        self.assertEqual(app.config["TRUSTED_PROXY_HOPS"], 0)
        with patch.dict("os.environ", {"GETPING_PROXY_HOPS": "1"}):
            app = self.make_app()
        self.assertEqual(app.config["TRUSTED_PROXY_HOPS"], 1)

    def test_new_installation_uses_instance_without_initializing_database(self):
        with patch("getping_admin.config.__file__", str(self.root / "getping_admin/config.py")):
            app = self.make_app()
        path = Path(app.config["DATABASE"])
        self.assertEqual(path, Path(app.instance_path) / "db_getping.db")
        self.assertFalse(path.exists())

    def test_existing_legacy_database_is_selected_without_modification(self):
        legacy = self.root / "database/db_getping.db"
        legacy.parent.mkdir()
        legacy.write_bytes(b"existing database sentinel")
        with patch("getping_admin.config.__file__", str(self.root / "getping_admin/config.py")):
            app = self.make_app()
        self.assertEqual(Path(app.config["DATABASE"]), legacy)
        self.assertEqual(legacy.read_bytes(), b"existing database sentinel")

    def test_explicit_database_overrides_legacy_and_environment(self):
        legacy = self.root / "database/db_getping.db"
        legacy.parent.mkdir()
        legacy.touch()
        environment_db = self.root / "environment.db"
        override_db = self.root / "override.db"
        with (
            patch("getping_admin.config.__file__", str(self.root / "getping_admin/config.py")),
            patch.dict("os.environ", {"GETPING_DATABASE": str(environment_db)}),
        ):
            self.assertEqual(Path(self.make_app().config["DATABASE"]), environment_db)
            self.assertEqual(
                Path(self.make_app(DATABASE=str(override_db)).config["DATABASE"]), override_db
            )
        self.assertFalse(environment_db.exists())
        self.assertFalse(override_db.exists())
