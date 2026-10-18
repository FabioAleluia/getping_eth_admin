import hashlib
import time
from flask import abort, current_app, request
from database.db import get_db


def enforce_limit(bucket, identity, limit):
    if limit <= 0:
        return
    window = int(time.time()) // current_app.config['RATE_WINDOW_SECONDS']
    identity = hashlib.sha256(identity.encode()).hexdigest()
    with get_db() as conn:
        conn.execute('DELETE FROM request_limits WHERE window < ?', (window - 1,))
        conn.execute('''INSERT INTO request_limits VALUES (?,?,?,1)
            ON CONFLICT(bucket,identity,window) DO UPDATE SET count=count+1''',
            (bucket, identity, window))
        count = conn.execute('SELECT count FROM request_limits WHERE bucket=? AND identity=? AND window=?',
                             (bucket, identity, window)).fetchone()[0]
    if count > limit:
        abort(429, description='Muitas requisições. Aguarde e tente novamente.')


def request_limits():
    if request.method != 'POST':
        return
    ip = request.remote_addr or 'unknown'
    if request.endpoint == 'auth.login':
        enforce_limit('login-ip', ip, current_app.config['LOGIN_RATE_LIMIT'])
        # Separate account budget also restricts attempts from multiple origins.
        username = request.form.get('username', '').strip().lower()[:254]
        enforce_limit('login-account', username, current_app.config['LOGIN_RATE_LIMIT'] * 3)
    elif request.blueprint == 'api':
        enforce_limit('api-ip', ip, current_app.config['API_RATE_LIMIT'])
