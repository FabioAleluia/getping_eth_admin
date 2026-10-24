# Auditoria das correções de integração — 23/10/2026

**Escopo:** conferir, no código atual, se cada achado de [ANALISE_INTEGRACAO_PRODUCAO_2026-10-22.md](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth_admin/docs/ANALISE_INTEGRACAO_PRODUCAO_2026-10-22.md) foi corrigido e se as afirmações de [CORRECOES_INTEGRACAO_2026-10-22.md](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth_admin/docs/CORRECOES_INTEGRACAO_2026-10-22.md) correspondem ao que existe.

**Estado examinado:** Admin no commit `9e46d73` (lado central do protocolo v2 já commitado). GetPing com as alterações **não commitadas** de `08132ba`, a maior parte implementada por mim na sessão anterior.

> [!IMPORTANT]
> **Parecer: ainda não está pronto para produção.** O Admin está correto. A maioria das correções do GetPing está certa e coberta por testes. Mas uma lacuna crítica anula a proteção principal do protocolo v2: **em produção, a verificação da assinatura Ed25519 é opcional**. Ela só acontece se `LICENCA_PUBLIC_KEY_FILE` estiver configurado, e nada impede o serviço de iniciar sem ela. Reproduzi isso em ensaio (seção 2).

---

## 1. Matriz por achado da análise

| ID | Situação | Observação |
|---|---|---|
| **A1** HTTPS | ⚠️ Parcial | **Admin:** correto. Em produção, não inicia sem HTTPS, fingerprint obrigatório e chave de assinatura ([`__init__.py:36-40`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth_admin/getping_admin/__init__.py#L36-L40)). **GetPing:** recusa HTTP no momento da chamada. Porém, o padrão continua `http://localhost:5001` e a validação de produção não roda na inicialização (ver L1). |
| **A2** Zero agentes | ✅ Correto | Zero bloqueia todos os agentes, inclusive os já existentes. Uma redução de cota bloqueia os excedentes em ordem de cadastro (FIFO). |
| **A3** `instancia_invalida` | ✅ Correto | É tratada como negativa autoritativa, sem tolerância offline. O conjunto de estados do Admin (`ativa/suspensa/expirada/cancelada`) está contido em `NEGATIVE_STATUSES`. |
| **A4** Cache | ⚠️ Parcial | O HMAC v2 cobre URL, check-in, documento central e revisão, e confere o `.server_fingerprint` atual ✅. Porém, o documento assinado **não é reverificado** na leitura, e as colunas de limites não são comparadas com ele (L4). |
| **A5** Login | ✅ Correto | O bloqueio global `conta:<username>` foi removido. Os limites por IP e por par IP/usuário continuam. Restaram constantes sem uso ([`security.py:12-13`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/security.py#L12-L13)). |
| **M1** UTC | ⚠️ Parcial | O vencimento usa `expira_em_iso` e a tolerância usa duração exata e `offline_ate_iso` ✅. Mas `ultimo_checkin` é gravado em **hora local** e lido como UTC (L6). |
| **M2** Concorrência | ⚠️ Parcial | A revisão é comparada após a rede ✅. Porém, a comparação e a escrita não são atômicas (L7). |
| **M3** Schema obrigatório | ❌ Só com chave pública | Sem `LICENCA_PUBLIC_KEY_FILE`, uma resposta incompleta ou não assinada continua sendo aceita, mesmo em produção (L1). |
| **M4** Coleta | ✅ Correto, com efeito colateral | Recebimento de agentes, persistência e coletor verificam a licença. Efeito colateral: o heartbeat para (L3). |
| **M5** Delimitador HMAC | ✅ Correto | Usa JSON canônico com domínio `GetPing/local_cache/v2`. |
| **D1** Autoridade | ⚠️ Parcial | Em produção, a rota ignora a URL digitada e a sincronização usa a configuração ✅. Mas a prova de origem central depende da chave pública, que é opcional (L1). |

---

## 2. Lacunas encontradas (por gravidade)

### 🔴 L1 — Assinatura Ed25519 é opcional em produção
**Onde:** [`licensing.py:171`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/licensing.py#L171) e [`licensing.py:313-330`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/licensing.py#L313-L330) (`if pub_file:`). A função [`validar_configuracao_producao()`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/config.py#L125-L158) só é chamada pelo comando `check-config`, nunca por `create_app()`, `wsgi.py`, `serve` ou `monitor`.

**Ensaio** ([probe_gaps.py](file:///home/fabioaleluia/.gemini/antigravity/brain/769b3dcf-eec3-4739-a8dd-bfe1f0837925/scratch/probe_gaps.py), banco temporário, `GETPING_ENV=production`, sem chave pública):
- `create_app()` iniciou normalmente.
- Uma resposta **não assinada** `{"valido": true, "limite_agentes": 99999, ...}` foi aceita. O resultado foi `valida=True`, com 99999 agentes.

**Impacto:** basta uma instalação manual, pelos fontes ou por gunicorn, sem a variável configurada. Nesse caso, nonce, assinatura, schema obrigatório e prova de origem ficam todos desligados, sem nenhum aviso. Só o `install.sh` protege, porque executa `check-config`.

**Correção:** fora de `development`, exigir a chave pública dentro de `licensing.py`, sem depender do `if`. Além disso, chamar `validar_configuracao_producao()` em `create_app()` e em `executar_monitor()`, abortando a inicialização se houver erro.

### 🔴 L2 — `cryptography` ausente no pacote
- [`pyproject.toml`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/pyproject.toml) não declara `cryptography`. O wheel instala, mas falha no import. O passo `smoke_wheel.py` do CI deve quebrar.
- O `requirements.txt` só passou a incluir a dependência ontem, depois do erro que você viu.
- [`build_release.py`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/scripts/build_release.py#L146-L149) não tem nenhuma inclusão explícita para `cryptography`. O relatório afirma que "as configurações de empacotamento agora incluem o suporte criptográfico", mas isso não é verdade. É preciso compilar e testar o binário Nuitka.

### 🟠 L3 — Heartbeat para quando a licença está inválida
O heartbeat é gravado em [`collector.py:143`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/monitoring/collector.py#L143), **depois** do `return` antecipado da licença ([linhas 60-67](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/monitoring/collector.py#L60-L67)). Com a licença inválida, o painel mostra *"A coleta não está ativa. Verifique o serviço de monitoramento"* (o aviso amarelo da sua captura) e `/status_server?ready=1` responde 503. Isso contradiz o relatório e leva o operador a investigar o serviço em vez da licença.

### 🟠 L4 — Documento assinado não é reverificado no cache
`verificar_status_licenca()` só confere o HMAC. A chave do HMAC é a `SECRET_KEY`, gravada em `.flask_secret` ao lado do banco e com o mesmo dono.

**Ensaio:** gravei `limite_agentes=123456` enquanto o documento assinado dizia 5, e recalculei o HMAC. Resultado: `valida=True` com 123456. O ataque exige ler o segredo, mas é exatamente o cenário de A4 que a assinatura central deveria cobrir.

**Correção:** na leitura, verificar a assinatura de `autorizacao_json` e exigir que limites, plano, vencimento, chave e fingerprint das colunas sejam iguais aos do documento.

### 🟡 L5 — Campos vinculados não são conferidos pelo cliente
O cliente confere apenas o `nonce`. Não compara `chave_licenca`, `fingerprint` nem `emissor` do documento com os próprios valores, embora o relatório diga que a assinatura "vincula" esses campos. Explorar isso exige repassar uma requisição com o nonce válido. Corrigir é barato.

### 🟡 L6 — `ultimo_checkin` em hora local lida como UTC
[`licensing.py:120,163`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/licensing.py#L163) usa `datetime.now()`. O ensaio gravou `19:02:45` com o UTC real em `22:02:45`. Em São Paulo, a janela offline fica 3 h menor; em fusos positivos, fica maior. A correção é usar `utc_now()`, ou preferir o `emitido_em_iso` assinado.

### 🟡 L7 — Concorrência: comparar e gravar não é atômico
[`licensing.py:401-410`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/licensing.py#L401-L410) lê a revisão e depois faz `DELETE`/`INSERT` em outra transação. A janela é pequena. A correção é refazer a comparação e a escrita dentro de um único `BEGIN IMMEDIATE`, com `WHERE revision=?`.

### 🟡 L8 — Cache legado aparece como "ADULTERADA"
Uma licença válida gravada antes do HMAC v2 aparece com a mensagem *"dados alterados localmente de forma não autorizada"*. O correto seria um estado como `revalidacao_necessaria`, com uma mensagem neutra. Do jeito atual, toda atualização vai parecer adulteração para o cliente.

### ⚪ Menores
- Respostas negativas não têm assinatura nem nonce verificados. Isso só permite negação de serviço por quem já intercepta o tráfego, que o HTTPS cobre.
- O coletor chama `verificar_status_licenca()` a cada 0,5 s e a cada resultado de sonda. Um cache curto (por exemplo, 5 s) resolve.
- [`app.py`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/app.py) agora assume `development` por padrão. Fui eu que alterei, para facilitar o uso local. A produção usa `wsgi.py` ou o `launcher`, mas o README cita `python app.py`. Convém documentar que ele não deve ser usado na VPS.

---

## 3. Afirmações do relatório CORRECOES que não conferem

| Afirmação | Realidade |
|---|---|
| "Produção não inicia com os requisitos de confiança ausentes" | Verdadeiro no Admin. **Falso no GetPing** (L1). |
| "O cliente verifica a identidade atual e a assinatura central" (cache) | A identidade é verificada. A assinatura só é verificada no recebimento, não na leitura (L4). |
| "O heartbeat de serviço continua ativo enquanto o coletor aguarda" | **Falso** (L3). |
| "`/status_server` informa `coleta_autorizada` e `status_licenca`" | **Não implementado.** [`agente.py:8-16`](file:///home/fabioaleluia/Dev/Projetos_Python/GetPing_eth/getping_v0.0.4/getping/routes/agente.py#L8-L16) não tem esses campos. |
| "GetPing 1.1.0" | `__version__ = "1.0.7"`. |
| "Dependências de runtime fixadas; empacotamento inclui suporte criptográfico" | **Falso** para `pyproject.toml` e `build_release.py` (L2). |
| "Formatação corrigida" | Não consegui verificar: o Ruff não está instalado nos venvs locais. |

> [!NOTE]
> Esse relatório foi commitado no Admin (`9e46d73`) **antes** das alterações do GetPing existirem. Na época, ele descrevia o lado do cliente como pronto sem que estivesse. Depois, eu implementei a maior parte, e as lacunas L1–L8 permanecem no estado atual.

---

## 4. Testes

O resultado das suítes reexecutadas está na resposta do chat. Os testes atuais passam porque **não cobrem** L1–L8. Os de integração sempre configuram a chave pública, e nenhum testa a produção sem ela, o heartbeat ou a reverificação do cache.

## 5. Ordem recomendada de correção

1. **L1 e L2** (bloqueadores): assinatura obrigatória fora de `development`, validação na inicialização, `cryptography` no `pyproject` e no build, e smoke test do wheel e do binário.
2. **L3 e L8** (operação/suporte): heartbeat antes da verificação da licença; estado `revalidacao_necessaria` para o cache legado.
3. **L4, L5 e L6** (integridade): reverificar o documento na leitura, conferir chave/fingerprint/emissor, usar UTC no check-in.
4. **L7**, itens menores e alinhamento do relatório (versão, `/status_server`).
5. Testes de regressão para cada item acima, inclusive "produção sem chave pública falha ao iniciar".
