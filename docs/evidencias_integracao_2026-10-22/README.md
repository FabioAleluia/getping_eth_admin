# Evidências da revisão de 22/10/2026

Relatório: [análise da integração](../ANALISE_INTEGRACAO_PRODUCAO_2026-10-22.md).

- `testes_admin.log` e `testes_getping.log`: suítes existentes, respectivamente 122 e 213 testes aprovados.
- `integracao.jsonl`: 15 registros de fluxos positivos e problemas reproduzidos.
- `transporte.jsonl`: quatro verificações do worker HTTP/TLS real em loopback.
- `dependencias_*.json`: respostas de pip-audit 2.10.1. A lista de produção do Admin foi expandida antes da consulta para incluir os requirements base e de produção; não inclui pip.
- `lint_*.log` e `formato_*.log`: verificações separadas de lint e formatação, sem modificar os fontes.

Para reproduzir, a partir da raiz do Admin, usando as dependências do venv do GetPing:

```bash
../GetPing_eth/getping_v0.0.4/venv/bin/python -B docs/evidencias_integracao_2026-10-22/auditar_integracao.py
../GetPing_eth/getping_v0.0.4/venv/bin/python -B docs/evidencias_integracao_2026-10-22/auditar_transporte.py
```

Os bancos, segredos e certificados são temporários. O primeiro script usa Flask test clients e substitui somente o transporte entre os projetos; não contata endpoints operacionais. O segundo precisa de OpenSSL e permissão para abrir portas aleatórias em loopback. Ele testa o subprocesso HTTP real, com uma CA temporária, sem usar a VPS.

Os scripts afirmam também os comportamentos defeituosos descritos no relatório. Terminarem sem exceção significa que os cenários foram reproduzidos, não que o produto esteja aprovado. Após correções, essas expectativas devem ser convertidas em testes de regressão do comportamento desejado.
