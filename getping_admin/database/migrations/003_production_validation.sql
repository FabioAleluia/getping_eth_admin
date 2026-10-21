-- Não corrige limites comerciais históricos. Gravações novas exigem inteiros.
DROP TRIGGER licencas_validate_insert;
DROP TRIGGER licencas_validate_update;
CREATE TRIGGER licencas_validate_insert BEFORE INSERT ON licencas
WHEN typeof(NEW.limite_hosts) != 'integer' OR typeof(NEW.limite_agentes) != 'integer'
 OR NEW.limite_hosts NOT BETWEEN 1 AND 10000 OR NEW.limite_agentes NOT BETWEEN 0 AND 10000
 OR NEW.data_expiracao IS NULL OR length(NEW.data_expiracao) != 19
 OR datetime(NEW.data_expiracao) IS NULL
BEGIN SELECT RAISE(ABORT, 'Dados de licença inválidos'); END;
CREATE TRIGGER licencas_validate_update BEFORE UPDATE ON licencas
WHEN typeof(NEW.limite_hosts) != 'integer' OR typeof(NEW.limite_agentes) != 'integer'
 OR NEW.limite_hosts NOT BETWEEN 1 AND 10000 OR NEW.limite_agentes NOT BETWEEN 0 AND 10000
 OR NEW.data_expiracao IS NULL OR length(NEW.data_expiracao) != 19
 OR datetime(NEW.data_expiracao) IS NULL
BEGIN SELECT RAISE(ABORT, 'Dados de licença inválidos'); END;

CREATE UNIQUE INDEX idx_users_username_identity ON admin_usuarios(lower(trim(username)));
CREATE UNIQUE INDEX idx_users_email_identity ON admin_usuarios(lower(trim(email)));
CREATE TRIGGER admin_identity_insert BEFORE INSERT ON admin_usuarios
WHEN typeof(NEW.username) != 'text' OR typeof(NEW.email) != 'text'
 OR length(trim(NEW.username)) = 0 OR length(trim(NEW.email)) = 0
 OR EXISTS (
 SELECT 1 FROM admin_usuarios WHERE
 lower(trim(username)) IN (lower(trim(NEW.username)),lower(trim(NEW.email)))
 OR lower(trim(email)) IN (lower(trim(NEW.username)),lower(trim(NEW.email)))
 )
BEGIN SELECT RAISE(ABORT, 'Identificador de autenticação já utilizado ou vazio'); END;
CREATE TRIGGER admin_identity_update BEFORE UPDATE OF username,email ON admin_usuarios
WHEN typeof(NEW.username) != 'text' OR typeof(NEW.email) != 'text'
 OR length(trim(NEW.username)) = 0 OR length(trim(NEW.email)) = 0
 OR EXISTS (
 SELECT 1 FROM admin_usuarios WHERE id != OLD.id AND (
 lower(trim(username)) IN (lower(trim(NEW.username)),lower(trim(NEW.email)))
 OR lower(trim(email)) IN (lower(trim(NEW.username)),lower(trim(NEW.email))))
 )
BEGIN SELECT RAISE(ABORT, 'Identificador de autenticação já utilizado ou vazio'); END;
