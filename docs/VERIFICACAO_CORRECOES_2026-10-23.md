# Verificação das correções — GetPing e GetPing Admin

> **Registro histórico da auditoria anterior às correções.** O estado posterior está em [Correções pendentes — 23/10/2026](CORRECOES_PENDENTES_2026-10-23.md); os resultados abaixo foram preservados como evidência dos defeitos encontrados.

**Data:** 23/10/2026. **Conclusão: não está tudo corrigido corretamente; ainda não recomendo liberar a versão atual para produção.**

A lacuna mais grave da auditoria anterior — aceitar autorização positiva sem chave pública em produção — foi fechada. Também foram corrigidos pontos importantes de integridade do cache, UTC, migração e concorrência na sincronização. Entretanto, a suíte do GetPing e o smoke test da distribuição ainda falham, e há pendências funcionais e de contrato reproduzidas abaixo.

## Referências e estado examinado

Comparados o [relatório de integração de 22/10](ANALISE_INTEGRACAO_PRODUCAO_2026-10-22.md), o [documento de correções](CORRECOES_INTEGRACAO_2026-10-22.md) e a [auditoria anterior de 23/10](../auditoria_correcoes_2026-10-23_19-39.md).

- **Admin:** commit `9e46d73`, com documentos/evidências locais não rastreados. O código funcional desse checkout não foi alterado nesta verificação.
- **GetPing:** base `08132ba`, incluindo as modificações locais atuais; versão declarada agora **1.1.0**. As alterações locais foram examinadas, não revertidas nem substituídas.
- Bancos, chaves e fingerprints usados nos ensaios são temporários. Não foi migrado nem inspecionado o conteúdo dos bancos operacionais.

A auditoria anterior não deve ser lida como descrição exata do estado atual: parte de suas lacunas foi corrigida depois. Esta revisão reconfirma os comportamentos no código que existe agora.

## Resultado dos testes e ferramentas

| Verificação | Resultado nesta revisão |
|---|---|
| Testes próprios do Admin | **127 passaram**; a descoberta incluiu mais 14 testes opcionais de integração ignorados por ausência da variável de checkout |
| Integração com os dois projetos, executada explicitamente | **14 passaram**, 2,562 s |
| GetPing | **217 executados: 216 passaram e 1 terminou com erro**, 63,464 s |
| `pip check` nos dois venvs | Sem incompatibilidades |
| Ruff 0.17.1 no Admin | Lint e formatação aprovados nos módulos/testes examinados |
| Ruff no GetPing | **3 erros de importação/formatação de imports**; **7 arquivos** precisam de formatação |
| `git diff --check` no GetPing | Uma linha em branco adicional no fim de `tests/test_producao.py` |
| Sintaxe shell de instalação/HTTPS/CLI | `bash -n` passou |
| Wheel GetPing | **Construído**, versão 1.1.0, a partir de cópia dos fontes em `/tmp` |
| Smoke test atual do wheel | **Falhou**: tenta salvar autorização sem chave pública em modo de produção |
| Binário Nuitka e instalação systemd real | Não recompilados/executados nesta verificação |

Os testes de integração existentes passaram, mas não cobrem todas as situações adicionais reproduzidas. Não é correto afirmar que todas as verificações de release estão aprovadas.

**Evidências:** [diretório da revisão](evidencias_verificacao_2026-10-23/), [suíte GetPing](evidencias_verificacao_2026-10-23/testes_getping.log), [suíte Admin](evidencias_verificacao_2026-10-23/testes_admin.log), [integração](evidencias_verificacao_2026-10-23/integracao.log), [ensaios adicionais](evidencias_verificacao_2026-10-23/lacunas.jsonl) e [smoke do wheel](evidencias_verificacao_2026-10-23/smoke_wheel.log).

## Conferência das lacunas L1–L8

| Item anterior | Situação atual | Evidência / ressalva |
|---|---|---|
| **L1 — assinatura opcional em produção** | **Corrigido para autorizações positivas e inicialização normal** | `create_app()` sem TESTING agora valida configuração; monitor também valida. Produção sem chave foi recusada no ensaio; resposta positiva sem chave não foi aceita. Negativas continuam sem verificação criptográfica, em caminho separado. |
| **L2 — dependência criptográfica ausente** | **Corrigido nos arquivos; validação da distribuição pendente** | `pyproject.toml` e requirements agora declaram cryptography/cffi/pycparser; build inclui cryptography e `_cffi_backend`. Wheel construiu, mas smoke falhou; o executável Nuitka não foi validado. |
| **L3 — heartbeat interrompido** | **Parcial** | O heartbeat continua e `/status_server` ganhou os dois campos previstos. Porém, o heartbeat registra a pausa comercial como erro técnico e readiness segue em 503. |
| **L4 — cache sem reverificar documento** | **Corrigido no cenário principal** | Assinatura central é verificada na leitura. Alterar cota e recalcular o HMAC local não liberou a licença. Ainda há condições opcionais nos metadados, tratadas em L5. |
| **L5 — chave/fingerprint/emissor não conferidos** | **Parcial** | Valores divergentes são comparados quando presentes; ausência desses campos não é rejeitada. Negativas também não passam por assinatura/nonce. |
| **L6 — check-in local interpretado como UTC** | **Corrigido** | Gravação positiva e atualização de estado usam `utc_now()`. Check-in gravado coincidiu com o minuto UTC do ensaio. |
| **L7 — comparação e escrita não atômicas** | **Corrigido nos helpers de sincronização; fluxo completo ainda parcial** | Os helpers agora usam `BEGIN IMMEDIATE` e revisão esperada; a integração de resposta antiga de sincronização passou. O formulário de ativação não transmite uma revisão capturada antes da rede e ainda sobrescreve uma ativação mais recente. |
| **L8 — cache antigo acusado de adulteração** | **Corrigido no cenário de migração** | Cache antigo sem comprovante/revisão retornou `revalidacao_necessaria`, com mensagem neutra. |

Também permanecem confirmadas as correções de bloqueio de zero agentes no recebimento, reconhecimento de `instancia_invalida`, remoção do bloqueio global de login e serialização HMAC canônica. A apresentação de zero na UI ainda está errada.

## Pendências reproduzidas, por prioridade

### P1 — A suíte GetPing e o smoke test de release precisam passar

**Arquivo:** `tests/test_producao.py:229`.

O teste novo chama:

```python
create_app(overrides={"GETPING_ENV": "production", "LICENCA_PUBLIC_KEY_FILE": None})
```

A assinatura da factory é `create_app(test_config=None)`. O teste termina com `TypeError`, antes de testar o bloqueio que pretendia cobrir. A factory real foi testada separadamente com a chamada correta e recusou configuração de produção sem chave; portanto, este erro não reabre L1, mas impede aprovar a suíte/CI.

**Smoke:** `scripts/smoke_wheel.py:68` continua criando licença sem assinatura/chave pública para um servidor temporário HTTP. Em ambiente controlado de produção, o teste do wheel recém-construído falhou com:

```text
ValueError: LICENCA_PUBLIC_KEY_FILE é obrigatório em produção.
```

**Ajuste necessário:** corrigir a chamada do teste e atualizar o smoke para usar central temporária HTTPS, chave pública e documento assinado, incluindo o subprocesso real. Um smoke de desenvolvimento separado pode existir, mas não comprova o protocolo de produção. Depois, compilar e validar o executável realmente distribuído; a presença de flags no script não certifica o resultado Nuitka.

### P1 — Prontidão continua falhando quando a licença está bloqueada

**Arquivos:** `getping/monitoring/collector.py:60–76`, `getping/monitoring/persistence.py:387–407`, `getping/routes/agente.py:14–23` e `packaging/install.sh:219–232`.

O heartbeat agora é gravado mesmo sem licença válida, o que é uma correção real. Porém, ele grava `erro="Coleta pausada: ..."`. `saude_monitor()` considera qualquer erro como falta de saúde, e readiness depende dessa saúde.

**Prova:** após cancelamento, um tick produziu:

```text
monitor ativo = true
monitor saudável = false
/status_server?ready=1 = 503
```

**Impacto:** o operador ainda pode receber sinal de falha do serviço quando a causa é comercial. O instalador depende desse healthcheck e pode terminar em falha/rollback numa instalação nova que ainda aguarda ativação. Essa consequência é inferida do fluxo do instalador; não foi feita uma instalação real nesta revisão.

**Ajuste necessário:** separar atividade/saúde técnica do processo e permissão comercial de coleta. O serviço deve continuar informando que está vivo e aguardando autorização, enquanto `coleta_autorizada=false` explica o bloqueio. Um healthcheck comercial separado pode falhar deliberadamente, mas não deve impedir a instalação/recuperação do serviço.

### P1 — Verificação de assinatura é desigual entre sucesso e bloqueio

**Arquivo:** `getping/licensing.py:360–423`.

A assinatura e o nonce são verificados apenas no ramo `valido=true`. Negativas reconhecidas são aplicadas sem assinatura e sem conferir a identidade da requisição.

**Prova:** uma resposta fabricada `403`, sem assinatura ou nonce, com `status="cancelada"` foi aplicada ao banco local. Não foi classificada como erro de transporte/contrato.

**Condição de exploração:** isso não demonstra interceptação de HTTPS nem acesso remoto anônimo ao cliente. Exige que uma resposta falsa chegue ao processamento, por exemplo através de endpoint/proxy comprometido ou fluxo simulado. O problema é o protocolo v2 prometer autenticação das autorizações e recusas, mas só verificar parte delas.

Há uma segunda falha de tratamento: com nonce atual e uma assinatura alterada, `validar_licenca_remota()` deixou escapar **`cryptography.exceptions.InvalidSignature`**. O `except` atual não captura essa classe. Os testes de documentos alterados existentes rejeitam antes pelo nonce e não exercitam essa combinação. Em uma chamada pelo formulário, isso pode resultar em 500 em vez de retorno controlado.

**Ajuste necessário:** verificar assinatura, nonce, chave, fingerprint e emissor antes de separar sucesso/negativa; capturar as exceções criptográficas e de contrato; não renovar check-in nem mudar estado em resposta não autenticada. Preservar respostas 429/5xx como falhas temporárias. Evitar modificar o dicionário assinado para trocar a mensagem de apresentação — o ramo `aguardando_vinculo` atualmente o modifica.

### P2 — Metadados vinculados ainda são opcionais

**Arquivo:** `getping/licensing.py:380–390` e `:641–654`.

O código usa condições como `if dados.get("fingerprint")`, em vez de exigir o campo. O teste com a chave privada temporária do fixture produziu três documentos assinados distintos, omitindo, respectivamente, `chave_licenca`, `fingerprint` e `emissor`. **Os três foram aceitos.**

A central atual inclui esses campos, portanto o ensaio não demonstra que um terceiro sem a chave privada consiga removê-los de um documento existente: isso invalidaria a assinatura. Ele comprova que a validação do schema v2 ainda não exige todo o vínculo prometido e pode aceitar uma emissão incompleta de uma autoridade confiável.

**Ajuste necessário:** schema obrigatório comum aos dois estados, com tipos e valores conferidos; validar também na leitura do cache. Tornar explícitos os campos de emissão e validade offline, suas faixas e consistência. Não aceitar ausência silenciosa dos vínculos centrais.

### P2 — Formulário de ativação ainda tem sobrescrita por resposta antiga

**Arquivo:** `getping/routes/licenca.py:48–50`.

A sincronização automática usa revisão esperada e está corrigida. O formulário, porém, consulta a rede e chama `salvar_licenca_local()` sem `expected_revision` capturada antes da chamada.

**Prova:** uma ativação de A ficou aguardando resposta. Antes de sua persistência, o fixture ativou B com documento válido real da central. A continuação do formulário de A respondeu 302 e sobrescreveu B. A chave mais recente não foi preservada.

**Ajuste necessário:** capturar o estado/revisão antes de consultar a central, conferir e gravar atomicamente no retorno e tratar descarte como resposta obsoleta. Aplicar tanto ao sucesso quanto ao cadastro de pendência. Não manter transação aberta durante a rede.

### P2 — Tarefas de coleta em andamento deixam de ser acompanhadas

**Arquivo:** `getping/monitoring/collector.py:62–64`.

`Future.cancel()` não encerra uma tarefa que já começou. O coletor chama cancel e limpa `em_voo` independentemente do resultado. Um future no estado em execução permaneceu rodando depois do bloqueio e foi removido do acompanhamento.

Isso não prova coleta infinita: os workers possuem seus próprios prazos, e a verificação na persistência ajuda a descartar resultados. Porém, a afirmação de que o coletor cancela/aguarda todas as tarefas em andamento ainda não corresponde ao código, e uma reativação rápida pode reagendar trabalho sem considerar o anterior.

**Ajuste necessário:** manter o acompanhamento dos futures iniciados até a conclusão/encerramento; descartar resultados após bloqueio; coordenar encerramento das sondas e retomada sem trabalho duplicado. Testar revogação com future já iniciado, não apenas revogação antes de um tick sem tarefas.

### P2 — Tela ainda chama zero agentes de “Ilimitado”

**Arquivo:** `getping/templates/configuracoes.html:260`.

A regra de bloqueio de zero agentes funcionou na integração. A tela de Configurações, entretanto, ainda renderiza `'Ilimitado'` quando o valor é zero.

**Prova:** com uma licença válida de zero agentes, o GET autenticado de Configurações retornou 200 e continha essa indicação. É contradição comercial/de interface, não uma nova prova de que o backend permite o primeiro agente.

**Ajuste necessário:** mostrar `0 (nenhum)` ou equivalente e conferir todas as apresentações de limites para evitar a mesma ambiguidade.

### P3 — Qualidade e documentação ainda precisam fechar com o código

- Ruff apontou imports em `getping/cli.py`, `getping/db/licenses.py` e `tests/test_producao.py`.
- Sete arquivos precisam de formatação: `getping/__init__.py`, `getping/config.py`, `getping/licensing.py`, `getping/routes/licenca.py`, `tests/test_n2_n3_n4_n5.py`, `tests/test_producao.py` e `tests/test_revisao_producao.py`.
- Gunicorn, Waitress e tzdata continuam usando intervalos em requirements/pyproject do cliente. A afirmação de que todas as dependências de runtime foram fixadas ainda precisa ser ajustada ou concluída.
- A versão declarada já é 1.1.0, e os campos de `/status_server` já existem: essas duas críticas específicas da auditoria anterior não devem continuar aparecendo como abertas.
- O comando `python app.py` assume desenvolvimento explicitamente. A documentação deve continuar distinguindo essa entrada da execução WSGI/launcher de produção.
- O código funcional atual do GetPing ainda não foi commitado. A release precisa conter as alterações efetivamente verificadas, inclusive `getping/license_protocol.py`, que está não rastreado.

## Ordem recomendada para fechar a versão

1. Corrigir o teste quebrado e o smoke de produção; executar CI e validar o artefato distribuído.
2. Separar prontidão técnica de bloqueio comercial e testar instalação sem licença cadastrada.
3. Unificar a verificação do protocolo v2 para sucesso/negativa e tratar assinaturas inválidas sem exceção externa.
4. Exigir metadados vinculados e proteger também a ativação manual por revisão.
5. Concluir o acompanhamento das tarefas de coleta, corrigir a UI de zero agentes e passar lint/formatação.
6. Atualizar o documento de correções com resultados reais e fechar a release completa.
7. Homologar domínio, TLS, firewall, migração, backup/restauração, runtime SQLite e carga na VPS. Esses passos não foram comprovados por esta revisão local.

**Parecer final:** houve correções reais e relevantes; a análise anterior de assinatura positiva opcional já ficou desatualizada. Ainda assim, há falhas de validação/release e pendências reproduzidas suficientes para manter a versão em homologação. Nenhuma correção funcional foi aplicada nesta auditoria.
