CREATE TABLE IF NOT EXISTS admin_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
 entity TEXT NOT NULL, entity_id TEXT NOT NULL, before_json TEXT, after_json TEXT,
 ip_origem TEXT, criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON admin_audit(criado_em);
CREATE TABLE IF NOT EXISTS request_limits (
 bucket TEXT NOT NULL, identity TEXT NOT NULL, window INTEGER NOT NULL,
 count INTEGER NOT NULL, PRIMARY KEY(bucket,identity,window)
);
CREATE TRIGGER IF NOT EXISTS licencas_validate_insert BEFORE INSERT ON licencas
WHEN NEW.limite_hosts NOT BETWEEN 1 AND 10000 OR NEW.limite_agentes NOT BETWEEN 0 AND 10000
 OR length(NEW.data_expiracao) != 19 OR datetime(NEW.data_expiracao) IS NULL
BEGIN SELECT RAISE(ABORT, 'Dados de licença inválidos'); END;
CREATE TRIGGER IF NOT EXISTS licencas_validate_update BEFORE UPDATE ON licencas
WHEN NEW.limite_hosts NOT BETWEEN 1 AND 10000 OR NEW.limite_agentes NOT BETWEEN 0 AND 10000
 OR length(NEW.data_expiracao) != 19 OR datetime(NEW.data_expiracao) IS NULL
BEGIN SELECT RAISE(ABORT, 'Dados de licença inválidos'); END;
CREATE INDEX IF NOT EXISTS idx_logs_event_time ON licenca_logs(licenca_id,evento,criado_em DESC);
