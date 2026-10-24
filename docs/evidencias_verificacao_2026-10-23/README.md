# Evidências da verificação de 23/10/2026

Relatório: [VERIFICACAO_CORRECOES_2026-10-23.md](../VERIFICACAO_CORRECOES_2026-10-23.md).

- `testes_admin.log`: 127 testes próprios aprovados e 14 testes de integração opcionais ignorados na descoberta padrão.
- `testes_getping.log`: 217 executados, com um erro de chamada da factory no teste novo.
- `integracao.log`: 14 testes cruzados aprovados quando executados explicitamente com o checkout do GetPing.
- `lacunas.jsonl`: reproduções adicionais; inclui correções confirmadas e comportamentos pendentes.
- `build_wheel.log`: construção isolada do wheel 1.1.0 em `/tmp`.
- `smoke_wheel.log`: falha do smoke atual em produção sem chave pública.
- `lint_*.log` / `formato_*.log`: verificações sem modificar os fontes.

Para reproduzir os ensaios adicionais a partir da raiz do Admin:

```bash
PYTHONDONTWRITEBYTECODE=1 ../GetPing_eth/getping_v0.0.4/venv/bin/python -B docs/evidencias_verificacao_2026-10-23/verificar_lacunas.py
```

O script cria bancos, usuários, chaves e identidades temporários; usa a central real por Flask test client e substitui somente o transporte da consulta. Não acessa a VPS. Algumas assertions confirmam o comportamento defeituoso atual: terminar sem erro significa reproduzir os cenários, não aprovação de segurança. Após correção, essas expectativas precisam ser invertidas em regressões do comportamento desejado.
