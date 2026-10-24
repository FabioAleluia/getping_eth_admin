#!/usr/bin/env bash
# Atalho para o script de deploy de produção
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/deploy/deploy_production.sh" "$@"
