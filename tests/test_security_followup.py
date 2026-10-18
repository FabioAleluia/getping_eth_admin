from time import time
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from database.db import get_db, audit
from tests.support import IsolatedDatabaseTestCase


class SecurityFollowupTests(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with get_db() as conn:
            for uid, role in ((2,'gestor'),(3,'assistente')):
                conn.execute('''INSERT INTO admin_usuarios
                    (id,nome,username,email,senha_hash,papel,ativo,trocar_senha,criado_em)
                    VALUES (?,?,?,?,?,?,1,0,'2026-01-01')''',
                    (uid,role,role,role+'@example.com',generate_password_hash('Test@123'),role))

    def post(self, path, **fields):
        return self.client.post(path,data=dict(fields,csrf_token='test-csrf'))

    def test_own_account_cannot_bypass_current_password_via_admin_editor(self):
        for uid in (1,2):
            self.authenticate(uid)
            result=self.post(f'/usuarios/{uid}/editar',nome='Changed',email='changed@example.com',nova_senha='Stolen@123')
            self.assertEqual(result.status_code,403)
            self.assertEqual(self.client.get(f'/usuarios/{uid}/editar').location,'/perfil')
        with get_db() as conn:
            self.assertEqual(conn.execute('SELECT nome FROM admin_usuarios WHERE id=1').fetchone()[0],'Admin Teste')

    def test_wrong_current_password_does_not_change_profile_password(self):
        self.authenticate(1)
        result=self.post('/perfil',nome='Admin',email='admin@example.com',senha_atual='wrong',nova_senha='Changed@123',confirma_senha='Changed@123')
        self.assertIn('Senha atual incorreta'.encode(),result.data)

    def test_idle_session_expires_and_cannot_refresh_itself(self):
        self.authenticate(1)
        now=time()
        with self.client.session_transaction() as sess:
            sess['issued_at']=now-4000
            sess['last_seen']=now-1801
        response=self.client.get('/usuarios/')
        self.assertEqual(response.status_code,302)
        self.assertIn('/login',response.location)
        with self.client.session_transaction() as sess:
            self.assertNotIn('user_id',sess)

    def test_absolute_session_expires_even_with_recent_activity(self):
        self.authenticate(1)
        now=time()
        with self.client.session_transaction() as sess:
            sess['issued_at']=now-86401
            sess['last_seen']=now-1
        self.assertIn('/login',self.client.get('/usuarios/').location)

    def test_activity_refreshes_idle_clock_without_extending_absolute_clock(self):
        self.authenticate(1)
        now=time()
        with self.client.session_transaction() as sess:
            sess['issued_at']=now-1000
            sess['last_seen']=now-100
        with patch('routes.auth.time',return_value=now):
            self.assertEqual(self.client.get('/usuarios/').status_code,200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['issued_at'],now-1000)
            self.assertEqual(sess['last_seen'],now)

    def test_legacy_sessions_require_login_again(self):
        self.authenticate(1)
        with self.client.session_transaction() as sess: sess.pop('issued_at')
        self.assertIn('/login',self.client.get('/usuarios/').location)

    def test_api_does_not_extend_panel_session(self):
        self.authenticate(1)
        now=time()
        with self.client.session_transaction() as sess: sess['last_seen']=now-100
        self.client.post('/api/v1/licenca/validar',json={'chave_licenca':'missing'})
        with self.client.session_transaction() as sess: self.assertEqual(sess['last_seen'],now-100)

    def test_revoke_all_sessions_also_rejects_saved_cookie(self):
        self.authenticate(1)
        other=self.app.test_client()
        other.set_cookie('session',self.client.get_cookie('session').value)
        self.assertEqual(self.post('/sessoes/encerrar').status_code,302)
        self.assertIn('/login',other.get('/usuarios/').location)
        self.assertIn('/login',self.client.get('/usuarios/').location)
        with get_db() as conn:
            self.assertEqual(conn.execute("SELECT actor_id FROM admin_audit WHERE action='revoke_sessions'").fetchone()[0],1)

    def test_revoke_sessions_requires_csrf(self):
        self.authenticate(1)
        self.assertEqual(self.client.post('/sessoes/encerrar').status_code,400)

    def test_login_and_logout_audit_has_actor_without_password(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess: token=sess['_csrf_token']
        self.client.post('/login',data={'username':'administrator','senha':'SenhaForte@123','csrf_token':token})
        with self.client.session_transaction() as sess: token=sess['_csrf_token']
        self.client.post('/logout',data={'csrf_token':token})
        with get_db() as conn:
            rows=conn.execute('SELECT * FROM admin_audit ORDER BY id').fetchall()
            self.assertEqual([r['action'] for r in rows],['login','logout'])
            self.assertEqual([r['actor_id'] for r in rows],[1,1])
            self.assertNotIn('SenhaForte',str([dict(r) for r in rows]))

    def test_audit_page_restricted_and_output_escaped(self):
        with get_db() as conn:
            audit(conn,'update','cliente',1,after={'nome':'<script>alert(1)</script>'})
        self.assertEqual(self.client.get('/auditoria/').status_code,302)
        for uid in (2,3):
            self.authenticate(uid)
            self.assertEqual(self.client.get('/auditoria/').status_code,403)
        self.authenticate(1)
        response=self.client.get('/auditoria/')
        self.assertEqual(response.status_code,200)
        self.assertNotIn(b'<script>alert(1)</script>',response.data)
        self.assertIn(b'&lt;script&gt;',response.data)

    def test_audit_filters_and_pagination(self):
        with get_db() as conn:
            for i in range(55): audit(conn,'update','cliente',i)
            audit(conn,'delete','usuario',3)
        self.authenticate(1)
        response=self.client.get('/auditoria/?acao=update&entidade=cliente')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'pagina=2',response.data)
        self.assertNotIn(b'<details',self.client.get('/auditoria/?acao=missing').data)
        self.assertEqual(self.client.get('/auditoria/?ator=invalid').status_code,400)
        self.assertEqual(self.client.get('/auditoria/?acao='+('x'*65)).status_code,400)

    def test_health_rejects_missing_migration_record(self):
        self.assertEqual(self.client.get('/health').status_code,200)
        with get_db() as conn: conn.execute('DELETE FROM schema_migrations WHERE version=1')
        self.assertEqual(self.client.get('/health').status_code,503)

    def test_security_check_is_read_only_and_does_not_expose_credentials(self):
        with get_db() as conn:
            before=conn.execute('SELECT COUNT(*) FROM admin_audit').fetchone()[0]
        result=self.app.test_cli_runner().invoke(args=['security-check'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertIn('Fingerprint obrigatório desativado',result.output)
        self.assertNotIn(self.app.secret_key,result.output)
        self.assertNotIn('SenhaForte',result.output)
        with get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_audit').fetchone()[0],before)
        self.assertNotEqual(self.app.test_cli_runner().invoke(args=['security-check','--strict']).exit_code,0)

    def test_security_check_reports_legacy_password_and_missing_migrations(self):
        with get_db() as conn:
            conn.execute('UPDATE admin_usuarios SET senha_hash=? WHERE id=1',(generate_password_hash('administrator'),))
        result=self.app.test_cli_runner().invoke(args=['security-check'])
        self.assertIn('senha antiga proibida',result.output)
        with get_db() as conn: conn.execute('DELETE FROM schema_migrations')
        self.assertNotEqual(self.app.test_cli_runner().invoke(args=['security-check']).exit_code,0)
