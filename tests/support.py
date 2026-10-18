import secrets
from time import time
import tempfile
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from app import create_app
from database.db import get_db


class IsolatedDatabaseTestCase(unittest.TestCase):
    """Every test owns a temporary database and context, even when run alone."""
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix='getping-test-')
        self.addCleanup(self.tempdir.cleanup)
        self.app = create_app({'TESTING':True, 'DATABASE':str(Path(self.tempdir.name)/'test.db'),
            'SECRET_KEY':secrets.token_hex(32), 'INIT_DB':True, 'SESSION_COOKIE_SECURE':False,
            'LOGIN_RATE_LIMIT':0, 'API_RATE_LIMIT':0})
        self.application = self.app
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        with get_db() as conn:
            conn.execute('''INSERT INTO admin_usuarios
                (nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                VALUES ('Admin Teste','administrator','administrator@getping.local',?,'superadmin',1,0,'2026-01-01 00:00:00')''',
                (generate_password_hash('SenhaForte@123'),))
        self.client = self.app.test_client()

    def authenticate(self, uid, client=None):
        client = client or self.client
        with get_db() as conn:
            version = conn.execute('SELECT auth_version FROM admin_usuarios WHERE id=?',(uid,)).fetchone()[0]
        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['auth_version'] = version
            sess['issued_at'] = sess['last_seen'] = time()
            sess['_csrf_token'] = 'test-csrf'
        return client
