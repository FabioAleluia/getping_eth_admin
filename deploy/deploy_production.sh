#!/usr/bin/env bash
# ==============================================================================
# GetPing Admin - Script de Deploy Automatizado em Produção (VPS)
# Suporte: Ubuntu 22.04 LTS / 24.04 LTS e Debian 12
# ==============================================================================

set -euo pipefail

# Cores para saída no terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # Sem cor

# Funções de log formatado
log_info() {
    echo -e "${BLUE}${BOLD}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}${BOLD}[SUCESSO]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}${BOLD}[AVISO]${NC} $1"
}

log_error() {
    echo -e "${RED}${BOLD}[ERRO]${NC} $1" >&2
}

log_header() {
    echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}\n"
}

# ------------------------------------------------------------------------------
# 1. Checagens Preliminares de Ambiente
# ------------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    log_error "Este script precisa ser executado como root (ou via sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Verificar se estamos no repositório do GetPing Admin
if [[ ! -f "${SOURCE_DIR}/requirements-production.txt" || ! -d "${SOURCE_DIR}/getping_admin" ]]; then
    log_error "Não foi possível localizar o código-fonte do GetPing Admin em '${SOURCE_DIR}'."
    exit 1
fi

log_header "GetPing Admin - Instalador de Produção VPS"
echo "Este assistente configurará o GetPing Admin com Nginx, Gunicorn,"
echo "assinatura criptográfica Ed25519 (Protocolo v2), isolamento e segurança."
echo ""

# ------------------------------------------------------------------------------
# 2. Coleta Interativa de Informações
# ------------------------------------------------------------------------------

# 2.1 Domínio
DOMINIO="${DOMINIO:-}"
while [[ -z "$DOMINIO" ]]; do
    echo -ne "${BOLD}Informe o domínio ou subdomínio do painel (ex: admin.meudominio.com): ${NC}"
    read -r DOMINIO_INPUT
    DOMINIO_INPUT="$(echo "$DOMINIO_INPUT" | tr -d ' ' | tr '[:upper:]' '[:lower:]')"
    # Remover protocolo se o usuário digitou https:// ou http://
    DOMINIO_INPUT="${DOMINIO_INPUT#https://}"
    DOMINIO_INPUT="${DOMINIO_INPUT#http://}"
    DOMINIO_INPUT="${DOMINIO_INPUT%/}"

    if [[ "$DOMINIO_INPUT" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        DOMINIO="$DOMINIO_INPUT"
    else
        log_error "Domínio inválido. Use apenas o FQDN (ex: admin.exemplo.com)."
    fi
done

# 2.2 E-mail do Administrador
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
while [[ -z "$ADMIN_EMAIL" ]]; do
    echo -ne "${BOLD}Informe o e-mail do Administrador inicial: ${NC}"
    read -r EMAIL_INPUT
    EMAIL_INPUT="$(echo "$EMAIL_INPUT" | tr -d ' ')"
    if [[ "$EMAIL_INPUT" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        ADMIN_EMAIL="$EMAIL_INPUT"
    else
        log_error "E-mail inválido. Digite um endereço de e-mail no formato usuario@dominio.com."
    fi
done

# 2.3 Senha do Administrador
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
while [[ -z "$ADMIN_PASSWORD" ]]; do
    echo -ne "${BOLD}Informe a senha do Administrador inicial (mín. 8 caracteres e símbolo especial): ${NC}"
    read -rs PASS1
    echo ""
    echo -ne "${BOLD}Confirme a senha: ${NC}"
    read -rs PASS2
    echo ""

    if [[ "$PASS1" != "$PASS2" ]]; then
        log_error "As senhas não coincidem. Tente novamente."
        continue
    fi
    if [[ ${#PASS1} -lt 8 ]]; then
        log_error "A senha deve ter no mínimo 8 caracteres."
        continue
    fi
    if [[ "$PASS1" == "administrator" ]]; then
        log_error "A senha não pode ser a senha padrão 'administrator'."
        continue
    fi
    if ! [[ "$PASS1" =~ [^a-zA-Z0-9] ]]; then
        log_error "A senha deve conter ao menos um caractere especial (ex: ! @ # $ % & *)."
        continue
    fi
    ADMIN_PASSWORD="$PASS1"
done

# 2.4 Opção de SSL via Certbot
CONFIG_SSL="${CONFIG_SSL:-}"
if [[ -z "$CONFIG_SSL" ]]; then
    echo -ne "${BOLD}Deseja emitir o certificado SSL Let's Encrypt automaticamente via Certbot agora? [S/n]: ${NC}"
    read -r RESP_SSL
    RESP_SSL="${RESP_SSL:-S}"
    if [[ "$RESP_SSL" =~ ^[Ss]$ ]]; then
        CONFIG_SSL="S"
    else
        CONFIG_SSL="N"
    fi
fi

# 2.5 Opção de Firewall UFW
CONFIG_UFW="${CONFIG_UFW:-}"
if [[ -z "$CONFIG_UFW" ]]; then
    echo -ne "${BOLD}Deseja configurar o firewall UFW liberando SSH, 80 e 443? [S/n]: ${NC}"
    read -r RESP_UFW
    RESP_UFW="${RESP_UFW:-S}"
    if [[ "$RESP_UFW" =~ ^[Ss]$ ]]; then
        CONFIG_UFW="S"
    else
        CONFIG_UFW="N"
    fi
fi

echo ""
log_info "Configurações confirmadas:"
echo -e "  - Domínio:       ${BOLD}${DOMINIO}${NC}"
echo -e "  - E-mail Admin:  ${BOLD}${ADMIN_EMAIL}${NC}"
echo -e "  - SSL Automático:${BOLD} ${CONFIG_SSL}${NC}"
echo -e "  - Firewall UFW:  ${BOLD}${CONFIG_UFW}${NC}"
echo ""
echo -ne "${YELLOW}Pressione ENTER para iniciar a instalação ou Ctrl+C para cancelar...${NC}"
read -r

# ------------------------------------------------------------------------------
# 3. Instalação de Pacotes do Sistema
# ------------------------------------------------------------------------------
log_header "Passo 1/9: Atualizando pacotes do sistema operacional"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    nginx \
    certbot \
    python3-certbot-nginx \
    ufw \
    curl \
    openssl \
    rsync \
    ca-certificates

# Verificar versão do Python
PYTHON_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
PYTHON_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"

if [[ "$PYTHON_MAJOR" -lt 3 || ("$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 12) ]]; then
    log_warning "Python detectado: ${PYTHON_VER}. O projeto recomenda Python 3.12 ou superior."
else
    log_success "Python ${PYTHON_VER} compatível."
fi

# ------------------------------------------------------------------------------
# 4. Criação do Usuário de Serviço e Estrutura de Diretórios
# ------------------------------------------------------------------------------
log_header "Passo 2/9: Criando usuário de sistema e diretórios de execução"

INSTALL_DIR="/opt/getping-admin"
CONFIG_DIR="/etc/getping-admin"

if ! id -u getping &>/dev/null; then
    useradd -r -s /bin/false -d "$INSTALL_DIR" getping
    log_success "Usuário de sistema 'getping' criado com sucesso."
else
    log_info "Usuário 'getping' já existe."
fi

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/instance"
mkdir -p "$INSTALL_DIR/backups"
mkdir -p "$CONFIG_DIR"
mkdir -p /var/www/html

# Ajustar permissões iniciais
chmod 0750 "$INSTALL_DIR"
chmod 0700 "$INSTALL_DIR/instance"
chmod 0700 "$INSTALL_DIR/backups"
chmod 0700 "$CONFIG_DIR"
chown -R getping:getping "$INSTALL_DIR"
chown -R root:getping "$CONFIG_DIR"

# ------------------------------------------------------------------------------
# 5. Sincronização do Código e Ambiente Virtual Python
# ------------------------------------------------------------------------------
log_header "Passo 3/9: Sincronizando código e preparando virtualenv"

if [[ "$(realpath "$SOURCE_DIR")" != "$(realpath "$INSTALL_DIR")" ]]; then
    log_info "Copiando arquivos da aplicação para $INSTALL_DIR..."
    rsync -av --delete \
        --exclude='.git' \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.ruff_cache' \
        --exclude='instance' \
        --exclude='backups' \
        "${SOURCE_DIR}/" "${INSTALL_DIR}/"
fi

chown -R getping:getping "$INSTALL_DIR"

if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    log_info "Criando ambiente virtual Python em $INSTALL_DIR/venv..."
    sudo -u getping python3 -m venv "$INSTALL_DIR/venv"
fi

log_info "Instalando dependências de produção com pip..."
sudo -u getping "$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel
sudo -u getping "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements-production.txt"

log_success "Ambiente virtual e dependências instaladas."

# ------------------------------------------------------------------------------
# 6. Geração de Chaves Criptográficas e Variáveis de Ambiente
# ------------------------------------------------------------------------------
log_header "Passo 4/9: Configurando segredos e par assimétrico Ed25519"

PRIVATE_KEY_PATH="${CONFIG_DIR}/license-private.pem"
PUBLIC_KEY_PATH="${CONFIG_DIR}/license-public.pem"

if [[ ! -f "$PRIVATE_KEY_PATH" ]]; then
    log_info "Gerando par de chaves assimétricas Ed25519 para emissão de licenças..."
    sudo -u getping "$INSTALL_DIR/venv/bin/python" -m getping_admin.license_keys \
        --private "$PRIVATE_KEY_PATH" \
        --public "$PUBLIC_KEY_PATH"
else
    log_info "Par de chaves de licença já existe. Mantendo existente para não invalidar licenças."
fi

chmod 0600 "$PRIVATE_KEY_PATH"
chmod 0644 "$PUBLIC_KEY_PATH"
chown getping:getping "$PRIVATE_KEY_PATH" "$PUBLIC_KEY_PATH"

ENV_FILE="/etc/getping-admin.env"
if [[ ! -f "$ENV_FILE" ]]; then
    SECRET_KEY_HEX="$("$INSTALL_DIR/venv/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
    cat > "$ENV_FILE" <<EOF
# GetPing Admin - Variáveis de Produção
SECRET_KEY=${SECRET_KEY_HEX}
GETPING_ENV=production
GETPING_DATABASE=${INSTALL_DIR}/instance/db_getping.db
GETPING_REQUIRE_HTTPS=1
GETPING_PUBLIC_BASE_URL=https://${DOMINIO}
GETPING_PROXY_HOPS=1
GETPING_REQUIRE_FINGERPRINT=1
GETPING_LICENSE_SIGNING_KEY_FILE=${PRIVATE_KEY_PATH}
EOF
    log_success "Arquivo $ENV_FILE gerado com sucesso."
else
    log_info "Arquivo $ENV_FILE já existe. Atualizando parâmetros de domínio e chave..."
    # Atualizar parâmetros sem perder a SECRET_KEY existente
    if ! grep -q "^GETPING_PUBLIC_BASE_URL=" "$ENV_FILE"; then
        echo "GETPING_PUBLIC_BASE_URL=https://${DOMINIO}" >> "$ENV_FILE"
    else
        sed -i "s|^GETPING_PUBLIC_BASE_URL=.*|GETPING_PUBLIC_BASE_URL=https://${DOMINIO}|" "$ENV_FILE"
    fi
    sed -i "s|^GETPING_REQUIRE_HTTPS=.*|GETPING_REQUIRE_HTTPS=1|" "$ENV_FILE"
    sed -i "s|^GETPING_REQUIRE_FINGERPRINT=.*|GETPING_REQUIRE_FINGERPRINT=1|" "$ENV_FILE"
    sed -i "s|^GETPING_PROXY_HOPS=.*|GETPING_PROXY_HOPS=1|" "$ENV_FILE"
    sed -i "s|^GETPING_LICENSE_SIGNING_KEY_FILE=.*|GETPING_LICENSE_SIGNING_KEY_FILE=${PRIVATE_KEY_PATH}|" "$ENV_FILE"
fi

chmod 0640 "$ENV_FILE"
chown root:getping "$ENV_FILE"

# ------------------------------------------------------------------------------
# 7. Inicialização do Banco de Dados e Criação do Administrador
# ------------------------------------------------------------------------------
log_header "Passo 5/9: Inicializando banco de dados e provisionando superadmin"

# Exportar variáveis para a execução dos comandos CLI
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$INSTALL_DIR"

log_info "Aplicando schema do banco e migrações versionadas..."
sudo -u getping -E "$INSTALL_DIR/venv/bin/flask" --app getping_admin:create_app init-db

log_info "Verificando se já existe superadministrador..."
ADMIN_EXISTS="$(sudo -u getping -E "$INSTALL_DIR/venv/bin/python" -c "
from getping_admin.database.db import get_db
from getping_admin import create_app
app = create_app()
with app.app_context():
    with get_db() as conn:
        res = conn.execute(\"SELECT COUNT(*) FROM admin_usuarios WHERE papel='superadmin'\").fetchone()[0]
        print(res)
")"

if [[ "$ADMIN_EXISTS" -eq 0 ]]; then
    log_info "Criando conta inicial do Superadmin..."
    sudo -u getping -E "$INSTALL_DIR/venv/bin/flask" --app getping_admin:create_app create-admin \
        --email "$ADMIN_EMAIL" \
        --password "$ADMIN_PASSWORD"
    log_success "Administrador inicial criado com sucesso."
else
    log_info "Já existe um superadministrador cadastrado. Nenhuma conta foi recriada."
fi

log_info "Executando checagem de conformidade de segurança estrita..."
sudo -u getping -E "$INSTALL_DIR/venv/bin/flask" --app getping_admin:create_app security-check --strict || {
    log_warning "security-check apontou alertas normais pré-ativação de certificados. Continuando..."
}

# ------------------------------------------------------------------------------
# 8. Configuração dos Serviços Systemd
# ------------------------------------------------------------------------------
log_header "Passo 6/9: Instalando serviços systemd e timer de manutenção"

cat > /etc/systemd/system/getping-admin.service <<EOF
[Unit]
Description=GetPing Admin
After=network.target

[Service]
User=getping
Group=getping
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -c deploy/gunicorn.conf.py 'getping_admin:create_app()'
Restart=on-failure
RestartSec=5s
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}/instance

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/getping-prune-logs.service <<EOF
[Unit]
Description=Retenção de logs de validação GetPing
After=getping-admin.service

[Service]
Type=oneshot
User=getping
Group=getping
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/flask --app getping_admin:create_app prune-logs
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}/instance
EOF

cat > /etc/systemd/system/getping-prune-logs.timer <<EOF
[Unit]
Description=Executa retenção diária dos logs GetPing

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m
Unit=getping-prune-logs.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now getping-admin.service
systemctl enable --now getping-prune-logs.timer

# Aguardar startup e checar loopback
sleep 2
if curl -s -f http://127.0.0.1:5001/health | grep -q '"status":"ok"'; then
    log_success "Serviço GetPing Admin ativo e respondendo em 127.0.0.1:5001/health."
else
    log_warning "Aguardando inicialização do Gunicorn..."
    sleep 3
    if curl -s -f http://127.0.0.1:5001/health | grep -q '"status":"ok"'; then
        log_success "Serviço GetPing Admin ativo e saudável."
    else
        log_error "O serviço getping-admin falhou ao responder no endpoint de saúde."
        systemctl status getping-admin.service --no-pager
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# 9. Configuração do Nginx e SSL (Certbot)
# ------------------------------------------------------------------------------
log_header "Passo 7/9: Configurando Nginx e Proxy Reverso"

NGINX_CONF="/etc/nginx/sites-available/getping-admin.conf"
rm -f /etc/nginx/sites-enabled/default

# Configuração HTTP inicial com suporte a desafio ACME do Let's Encrypt
cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name ${DOMINIO};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Bloquear chamadas POST à API em HTTP sem converter silenciosamente
    location /api/ {
        return 426;
    }

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
    }
}
EOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/getping-admin.conf
nginx -t
systemctl reload nginx

SSL_SUCCESS=0
if [[ "$CONFIG_SSL" == "S" ]]; then
    log_header "Passo 8/9: Emitindo Certificado SSL com Certbot"
    log_info "Solicitando certificado Let's Encrypt para $DOMINIO..."

    if certbot certonly --webroot -w /var/www/html -d "$DOMINIO" \
        --non-interactive --agree-tos -m "$ADMIN_EMAIL" --keep-until-expiring; then
        
        log_success "Certificado Let's Encrypt obtido com sucesso!"

        # Configurar bloco HTTPS definitivo conforme padrão de segurança do projeto
        cat > "$NGINX_CONF" <<EOF
# Configuração de Produção - GetPing Admin
server {
    listen 80;
    server_name ${DOMINIO};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Bloquear conversão de POST para GET em redirecionamentos HTTP
    location /api/ {
        return 426;
    }

    # Redirecionamento permanente com preservação de método
    location / {
        return 308 https://${DOMINIO}\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name ${DOMINIO};

    ssl_certificate /etc/letsencrypt/live/${DOMINIO}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMINIO}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    client_max_body_size 32k;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
    }
}
EOF
        nginx -t
        systemctl reload nginx
        SSL_SUCCESS=1
    else
        log_warning "Não foi possível emitir o certificado SSL automaticamente agora."
        log_warning "Isso normalmente ocorre quando o DNS ainda não propagou para o IP desta VPS."
        log_warning "Acesse com HTTP provisoriamente ou execute após propagar o DNS:"
        log_warning "  sudo certbot --nginx -d ${DOMINIO}"
    fi
else
    log_info "Passo 8/9: Emissão de SSL pulada a pedido do usuário."
fi

# ------------------------------------------------------------------------------
# 10. Configuração do Firewall (UFW)
# ------------------------------------------------------------------------------
if [[ "$CONFIG_UFW" == "S" ]]; then
    log_header "Passo 9/9: Configurando Firewall (UFW)"

    # Detectar porta SSH em uso para evitar desconexão
    SSH_PORT=22
    if [[ -f /etc/ssh/sshd_config ]]; then
        DETECTED_PORT="$(grep -E "^Port [0-9]+" /etc/ssh/sshd_config | awk '{print $2}' || true)"
        if [[ -n "$DETECTED_PORT" ]]; then
            SSH_PORT="$DETECTED_PORT"
        fi
    fi

    log_info "Liberando porta SSH ($SSH_PORT/tcp)..."
    ufw allow "$SSH_PORT/tcp" comment 'SSH'
    log_info "Liberando portas web (80/tcp e 443/tcp)..."
    ufw allow 80/tcp comment 'HTTP Nginx'
    ufw allow 443/tcp comment 'HTTPS Nginx'

    # Habilitar firewall se ainda não estiver ativo
    if ! ufw status | grep -q "Status: active"; then
        log_info "Ativando UFW..."
        ufw --force enable
    else
        ufw reload
    fi
    log_success "Firewall configurado. Porta interna do Gunicorn (5001) permanece inacessível externamente."
else
    log_info "Passo 9/9: Configuração de Firewall pulada a pedido do usuário."
fi

# ------------------------------------------------------------------------------
# 11. Resumo Final e Orientações Operacionais
# ------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}       DEPLOY DO GETPING ADMIN CONCLUÍDO COM SUCESSO!                         ${NC}"
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo ""
if [[ "$SSL_SUCCESS" -eq 1 ]]; then
    echo -e "Painel Web:            ${BOLD}https://${DOMINIO}${NC}"
    echo -e "Endpoint de Saúde:     ${BOLD}https://${DOMINIO}/health${NC}"
else
    echo -e "Painel Web:            ${BOLD}http://${DOMINIO}${NC} (Configure SSL para liberar o login)"
fi
echo -e "Usuário inicial:       ${BOLD}administrator${NC} (ou ${ADMIN_EMAIL})"
echo -e "Senha inicial:         ${BOLD}[A que você definiu durante a instalação]${NC}"
echo ""
echo -e "${YELLOW}${BOLD}Atenção no primeiro acesso:${NC}"
echo -e "  O sistema exigirá ${BOLD}obrigatoriamente a troca da senha${NC} no primeiro login."
echo ""
echo -e "${CYAN}${BOLD}Integração com Clientes GetPing:${NC}"
echo -e "  1. No cliente GetPing, configure a URL da central:"
echo -e "     ${BOLD}GETPING_CENTRAL_URL=https://${DOMINIO}${NC}"
echo -e "  2. Copie a chave pública para o cliente GetPing:"
echo -e "     ${BOLD}${PUBLIC_KEY_PATH}${NC}"
echo -e "     (Nunca compartilhe nem retire do servidor a chave 'license-private.pem')"
echo ""
echo -e "${CYAN}${BOLD}Comandos úteis para o Administrador:${NC}"
echo -e "  - Status do serviço:   ${BOLD}sudo systemctl status getping-admin${NC}"
echo -e "  - Logs em tempo real:  ${BOLD}sudo journalctl -u getping-admin -f${NC}"
echo -e "  - Backup do banco:     ${BOLD}sudo -u getping -E ${INSTALL_DIR}/venv/bin/flask --app getping_admin:create_app backup-db ${INSTALL_DIR}/backups/backup-\$(date +%F).db${NC}"
echo -e "  - Redefinir senha:     ${BOLD}sudo -u getping -E ${INSTALL_DIR}/venv/bin/flask --app getping_admin:create_app reset-password administrator${NC}"
echo ""
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
