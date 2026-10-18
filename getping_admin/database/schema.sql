-- Schema inicial do GetPing Admin

CREATE TABLE IF NOT EXISTS admin_usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    senha_hash    TEXT NOT NULL,
    papel         TEXT NOT NULL CHECK(papel IN ('superadmin', 'gestor', 'assistente')) DEFAULT 'assistente',
    ativo         INTEGER NOT NULL DEFAULT 1,
    trocar_senha  INTEGER NOT NULL DEFAULT 1,
    criado_em     TEXT NOT NULL,
    auth_version  INTEGER NOT NULL DEFAULT 0,
    ultimo_login  TEXT
);

CREATE TABLE IF NOT EXISTS clientes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_empresa      TEXT NOT NULL,
    responsavel_nome  TEXT NOT NULL,
    responsavel_email TEXT,
    telefone          TEXT,
    cnpj_cpf          TEXT,
    ativo             INTEGER NOT NULL DEFAULT 1,
    criado_em         TEXT NOT NULL,
    observacoes       TEXT
);

CREATE TABLE IF NOT EXISTS licencas (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id           INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    chave_licenca        TEXT NOT NULL UNIQUE,
    tipo_plano           TEXT NOT NULL CHECK(tipo_plano IN ('Trial', 'Basico', 'Profissional', 'Enterprise')) DEFAULT 'Basico',
    limite_hosts         INTEGER NOT NULL DEFAULT 10,
    limite_agentes       INTEGER NOT NULL DEFAULT 5,
    status               TEXT NOT NULL CHECK(status IN ('ativa', 'suspensa', 'expirada', 'cancelada')) DEFAULT 'ativa',
    data_emissao         TEXT NOT NULL,
    data_expiracao       TEXT NOT NULL,
    ultimo_checkin_em    TEXT,
    instancia_fingerprint TEXT,
    observacoes          TEXT
);

CREATE TABLE IF NOT EXISTS licenca_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    licenca_id    INTEGER REFERENCES licencas(id) ON DELETE SET NULL,
    chave_usada   TEXT,
    evento        TEXT NOT NULL,
    ip_origem     TEXT,
    detalhes      TEXT,
    criado_em     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_licencas_chave ON licencas(chave_licenca);
CREATE INDEX IF NOT EXISTS idx_licencas_cliente ON licencas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_logs_licenca ON licenca_logs(licenca_id);
CREATE INDEX IF NOT EXISTS idx_logs_data ON licenca_logs(criado_em);
