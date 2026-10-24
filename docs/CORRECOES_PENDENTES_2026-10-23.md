# Correções das pendências — GetPing e GetPing Admin

Data: 23/10/2026. Referência: [verificação anterior](VERIFICACAO_CORRECOES_2026-10-23.md).

## Alterações aplicadas

As falhas funcionais pendentes estavam no cliente GetPing. O Admin continua emitindo o protocolo v2, e recebeu dez testes adicionais de integração com o cliente. A versão do cliente continua 1.1.0; não houve deploy, migração de banco operacional, troca de segredo ou recriação de identidade.

| Prioridade | Pendência | Correção |
|---|---|---|
| P1 | Contrato desigual entre sucesso e bloqueio | `getping/license_validation.py` centraliza o schema, a assinatura Ed25519 e os vínculos. Respostas positivas e negativas exigem assinatura, chave, fingerprint, emissor, nonce e emissão UTC em produção. |
| P1 | Assinatura inválida podia gerar erro interno | Exceções criptográficas são convertidas em falha controlada. Documento inválido não altera licença nem renova check-in. Respostas 429/5xx continuam temporárias. |
| P1 | Readiness falhava por bloqueio comercial | O coletor mantém heartbeat técnico saudável durante pausa por licença. A API continua indicando `coleta_autorizada=false`; acesso e coleta continuam bloqueados pela licença. |
| P1 | Teste e smoke de release quebrados | Corrigida a chamada `create_app(test_config=...)`. Smoke usa HTTPS verificado, certificado temporário e documentos assinados, com workers reais fora do checkout. |
| P2 | Metadados opcionais e cache incompleto | O mesmo validador é usado na rede, gravação e leitura do cache. Datas, cotas e vínculos obrigatórios são conferidos. O check-in assinado deve coincidir com o comprovante; documentos antigos exigem revalidação. |
| P2 | Ativação antiga sobrescrevia alteração recente | O formulário captura a revisão antes da rede e transmite `expected_revision` à gravação atômica. Sucesso e pendência antigos são descartados. |
| P2 | Futures iniciados desapareciam do acompanhamento | Tarefas iniciadas continuam ocupando slots até terminar; resultados marcados durante bloqueio são descartados mesmo após reativação. Cancelamento de tarefa ainda em fila é respeitado. |
| P2 | Zero agentes exibido como ilimitado | A tela mostra `0 (nenhum)`. O bloqueio do primeiro agente com cota zero permanece. |
| P3 | Lint, formatação e versões | Imports/formatação corrigidos; Gunicorn 26.2.0, Waitress 3.0.2 e tzdata 2026.5 fixados em requirements e pyproject do cliente, correspondendo às versões locais verificadas. |

O documento de pendência é armazenado sem trocar sua mensagem dentro do JSON assinado. A orientação para o usuário é apresentada separadamente. O cliente só admite respostas sem assinatura no modo explícito de desenvolvimento, sem chave pública configurada; produção não recebe esse atalho.

## Verificação reproduzível

Os testes usam bancos, chaves e fingerprints descartáveis. As evidências ficam em `docs/evidencias_correcoes_pendentes_2026-10-23/` no GetPing Admin.

| Verificação | Resultado |
|---|---|
| GetPing — suíte existente | 217 testes passaram, tanto no staging quanto no checkout corrigido |
| GetPing — quatro novos testes criptográficos | 4 passaram; incluídos na descoberta padrão da CI do cliente |
| Admin — suíte própria | 127 passaram; a descoberta também encontra 24 integrações opcionais, ignoradas quando o checkout do cliente não está configurado |
| Integração explícita entre os checkouts | 24 passaram, incluindo 10 novos testes para estas pendências |
| Ruff 0.17.1 | Lint e formatação aprovados nos dois projetos |
| Dependências e shell | `pip check` nos dois venvs, `git diff --check` e `bash -n` nos scripts do cliente aprovados |
| Wheel GetPing 1.1.0 | Construído; smoke fora do checkout passou com TLS verificado, assinatura central, subprocesso de licença, worker persistente de sonda e preservação do cache em HTTP 503 |
| Wheel Admin | Construído; recursos, templates, CLI, schema, migração e API verificados fora do checkout |
| Binário Nuitka | Compilação standalone 4.3.1 concluída; CLI, web, monitor, prontidão sem licença, ativação assinada, recusa de assinatura inválida e workers compilados de licença/sonda passaram no smoke |

Para executar a integração a partir do GetPing Admin:

```bash
GETPING_CLIENT_SOURCE=/caminho/absoluto/GetPing \
  /caminho/GetPing/venv/bin/python -B -W error::ResourceWarning -m unittest \
  integration_tests.test_protocol_v2 integration_tests.test_pending_corrections -v
```

Para verificar a distribuição do cliente:

```bash
python scripts/smoke_wheel.py dist/getping-1.1.0-py3-none-any.whl
# Acrescente --binary /caminho/launcher.dist/getping para testar CLI e workers compilados.
```

O teste precisa de OpenSSL e permissão para abrir portas temporárias em `127.0.0.1`. O certificado gerado é confiado apenas no ambiente descartável do teste; a validação TLS não é desativada. O modo `--binary` também sobe web e monitor temporários para verificar prontidão sem licença, ativação com assinatura válida e rejeição de assinatura de outra chave no próprio executável.

O binário foi construído em `/tmp/getping-fixes-20261023-3jjnwmet/build/nuitka/1.1.0-20261023T232118Z/launcher.dist/getping`. O pacote de distribuição e seus hashes ficam em `/tmp/getping-pending-releases/`. Esses artefatos locais não foram publicados.

## Limites da liberação

As correções de código e os resultados locais não comprovam a implantação na VPS. Permanecem necessários: configuração real de domínio e TLS, chave pública correspondente à central, firewall e proxy, permissões dos serviços, backup/restauração, migração ensaiada em cópia e teste de carga/disco na infraestrutura de destino.

A release deve incluir todos os arquivos novos e modificados, inclusive `getping/license_protocol.py` e `getping/license_validation.py`. Não foi criado commit ou publicada release. Os relatórios e scripts de reprodução de falhas anteriores foram preservados como histórico; não são testes de aceitação do código corrigido.
