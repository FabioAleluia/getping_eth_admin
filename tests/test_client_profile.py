import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from getping_admin.client_profile import export_profile
from getping_admin.prepare_local_https import prepare


class TestClientProfile(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / "signing.pem"
        self.private = Ed25519PrivateKey.generate()
        self.key.write_bytes(
            self.private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.key.chmod(0o600)

    def test_export_public_only_preserves_signer(self):
        original = self.key.read_bytes()
        output = export_profile(self.root / "profile", "https://192.168.10.108", self.key)
        self.assertEqual({p.name for p in output.iterdir()}, {"central.json", "license-public.pem"})
        self.assertEqual(self.key.read_bytes(), original)
        public = serialization.load_pem_public_key((output / "license-public.pem").read_bytes())
        self.assertEqual(
            public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
            self.private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ),
        )
        with self.assertRaises(FileExistsError):
            export_profile(output, "https://192.168.10.108", self.key)

    def test_reject_http_before_output(self):
        with self.assertRaises(ValueError):
            export_profile(self.root / "bad", "http://192.168.10.108:5001", self.key)
        self.assertFalse((self.root / "bad").exists())

    def test_prepare_https_san_ca_and_private_separation(self):
        original = self.key.read_bytes()
        output = prepare(self.root / "tls", "https://192.168.10.108", self.key)
        server = x509.load_pem_x509_certificate((output / "server.crt").read_bytes())
        ca = x509.load_pem_x509_certificate((output / "ca.crt").read_bytes())
        self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertIn(
            "192.168.10.108",
            str(server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value),
        )
        server.verify_directly_issued_by(ca)
        profile = output / "client-profile"
        self.assertEqual(
            {p.name for p in profile.iterdir()},
            {"central.json", "license-public.pem", "license-ca.crt"},
        )
        for file in profile.iterdir():
            self.assertNotIn(b"PRIVATE KEY", file.read_bytes())
        self.assertEqual(self.key.read_bytes(), original)
        self.assertEqual((output / "ca-private.pem").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            prepare(output, "https://192.168.10.108", self.key)
