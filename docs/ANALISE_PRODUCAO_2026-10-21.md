# Avaliação de prontidão para produção — 21/10/2026

> Atualização: as correções do grupo 1 foram implementadas após esta avaliação.
> Consulte [as alterações e o procedimento da migração 003](CORRECOES_CODIGO_2026-10-21.md).
> Os achados e resultados abaixo descrevem o estado examinado antes dessas correções.

**Parecer: o projeto tem uma boa base para operar em uma VPS, mas eu ainda não liberaria a versão atual para produção pública sem corrigir os problemas abaixo e validar a implantação. Pode seguir para homologação.**

A arquitetura Flask + Gunicorn + Nginx + SQLite é compatível com uma implantação em um único servidor e carga moderada, condicionada a medições. Não há evidência nesta revisão que justifique reescrever o projeto ou migrar imediatamente para outro banco. Também não há dados que permitam prometer quantidade de clientes, requisições por segundo ou disponibilidade.

## Escopo e evidências

Revisados: factory/configuração, autenticação e sessões, permissões, clientes, usuários, licenças, API, validações, auditoria, acesso SQLite, schema/migrações, templates/JavaScript, empacotamento, CI, exemplos de deploy e documentação. A avaliação considera os arquivos atuais do workspace, incluindo alterações ainda sem commit, e reavalia os relatórios de 20/10.

Validações executadas nesta revisão:

| Verificação | Resultado |
|---|---|
| `venv/bin/python -m unittest discover -v` | **102 testes passaram**, em 23,789 s |
| `venv/bin/python -m pip check` | Sem dependências instaladas incompatíveis |
| `git diff --check` | Sem erros |
| Ensaios adicionais em SQLite temporário | Reproduzidos os problemas de zero agentes, colisão de login, dado legado inválido, diagnóstico incompleto e exclusão inexistente |
| Runtime local | Python 3.12.3; SQLite 3.45.1 |

Nenhum ensaio usou o banco operacional. Não foram alterados código funcional, configuração operacional, serviço ou banco. Este relatório é o único arquivo adicionado por esta análise.

Limites: não houve acesso à VPS, inspeção de certificado/firewall, teste do cliente GetPing real, teste de carga representativo ou auditoria dos registros do banco operacional. Ruff, Gunicorn e ferramentas de auditoria/build não estão disponíveis no venv. A tentativa de obter ferramentas em `/tmp` falhou na resolução de `ruff==0.17.1`; isso não demonstra que a versão não exista no índice público. Lint, formatação, auditoria automatizada de vulnerabilidades, novo build de wheel e execução WSGI real **não foram revalidados**. A aprovação desses passos no relatório anterior é histórica.

## O que já está bem implementado

- Organização em pacote, factory e blueprints; `app.py` funciona como entrada pequena de compatibilidade.
- Consultas com parâmetros nos fluxos examinados; fragmentos SQL dinâmicos relevantes vêm de constantes internas.
- Hash de senha pelo Werkzeug; rejeição da senha universal antiga; provisionamento administrativo explícito por CLI.
- CSRF nas mutações do painel, logout por POST, renovação da sessão no login e cookies com HttpOnly/SameSite.
- Sessões com expiração por inatividade e prazo absoluto; revogação por versão após mudanças administrativas e de senha.
- Permissões verificadas no servidor; assistentes não alteram condições comerciais por padrão.
- Limite de payload, validação de campos, respostas JSON de erro na API e cabeçalhos de segurança.
- Transações com commit/rollback e fechamento explícitos; foreign keys habilitadas; migrações fora da inicialização normal do servidor.
- Backup pelo mecanismo SQLite, sem sobrescrita do destino, e comando de retenção dos logs de validação.
- Auditoria administrativa na mesma transação da alteração, evitando gravar senhas/hashes nesses eventos.
- Exemplos de Nginx HTTPS, Gunicorn em loopback e systemd com usuário dedicado, umask e restrições de escrita.
- CI previsto para lint, formatação, testes e verificação da distribuição instalada.

Esses controles aumentam a confiança, mas os 102 testes não cobrem todos os casos comprovados nesta revisão.

## Correções anteriores confirmadas

Não devem continuar sendo apresentadas como falhas abertas sem considerar a versão atual:

| Achado de 20/10 | Estado atual |
|---|---|
| Perda de `auth_version` na reconstrução legada | Implementação preserva a coluna, sequência e objetos explícitos; regressões de schema e cookie revogado passaram |
| Bloqueio global dirigido por identificador de login | Orçamento global removido; cota por origem permanece; regressões passaram |
| Ausência de controle HTTPS na aplicação | Controle implementado e testado; sua ativação e o TLS real ainda dependem da implantação |
| Primeira máquina reivindicando licença nova | Licenças novas aguardam autorização explícita; regressões de autorização e liberação passaram |
| Limpeza de contadores sem índice por janela | Migração 002 agora cria `idx_request_limits_window`; continua havendo escrita por requisição |

## Problemas que eu corrigiria antes da publicação

### P1 — Transporte e execução precisam ser configurados para produção

**Tipo:** condição de implantação com impacto alto se ignorada.

`getping_admin/config.py` mantém `GETPING_REQUIRE_HTTPS=0` como padrão; `.env.example` também. Definir apenas `GETPING_ENV=production` não ativa essa exigência. `python app.py`/`python -m getping_admin` abre o servidor de desenvolvimento em `0.0.0.0:5001`.

O arquivo `iniciar_app.md` exporta ambiente de desenvolvimento e gera uma chave nova a cada execução do trecho. Isso serve a testes, mas não deve orientar o serviço de produção: o segredo precisa ser estável e protegido. Gerá-lo novamente encerra a validade dos cookies anteriores.

**Liberação:** Gunicorn em `127.0.0.1:5001`, Nginx com certificado válido, backend inacessível externamente, ambiente persistente e cliente usando HTTPS com verificação de certificado. Para exatamente um proxy conforme o exemplo:

```ini
GETPING_ENV=production
GETPING_REQUIRE_HTTPS=1
GETPING_PUBLIC_BASE_URL=https://SEU-DOMINIO-REAL
GETPING_PROXY_HOPS=1
GETPING_DATABASE=/DIRETORIO-OPERACIONAL/db_getping.db
SECRET_KEY=SEGREDO-ALEATORIO-PERSISTENTE
```

Os valores acima são um modelo, não configuração pronta para copiar. `.env` não é carregado implicitamente pelo projeto. Use o ambiente efetivo do processo ou `EnvironmentFile` do systemd. A documentação oficial do [Flask exige servidor de produção](https://flask.palletsprojects.com/en/stable/deploying/) e explica os cuidados com a [confiança no proxy](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/).

### P2 — Zero agentes vira cinco no formulário de edição

**Tipo:** bug funcional/comercial, prioridade alta para a liberação.

**Local:** `getping_admin/templates/licencas/form.html:56`.

`{{ licenca.limite_agentes or 5 }}` usa o fallback também para zero, que é permitido. Em fixture com zero no banco, GET da edição retornou `value="5"`. Salvar outro campo pelo formulário pode aumentar involuntariamente o direito comercial.

**Correção:** usar fallback somente para valor ausente/nulo e preservar zero. Acrescentar regressão de renderização e salvamento sem alterar limites.

### P3 — Login aceita identificadores ambíguos

**Tipo:** integridade/autenticação, prioridade média.

**Locais:** `getping_admin/routes/auth.py:43`, cadastro/edição em `routes/usuarios.py`, perfil e constraints de `database/schema.sql`.

Username e e-mail têm unicidade separada. O login busca `username = ? OR email = ?` e pega a primeira linha. O cadastro não verifica colisão cruzada. No ensaio, foi possível inserir uma conta cujo username era o e-mail de outra; a busca encontrou duas contas.

**Impacto:** autenticação ambígua, possível recusa de senha correta e confusão operacional. Não foi demonstrado acesso à conta alheia ou elevação de privilégio. Há também normalização desigual: cadastro administrativo converte e-mail para minúsculas, enquanto perfil e login não seguem a mesma regra.

**Correção:** definir namespace inequívoco e normalização consistente; por exemplo, username sem `@`, e-mail normalizado e migração/conferência dos identificadores existentes. Aplicar a regra em cadastro, edição, perfil e CLI, com proteção no banco contra concorrência. Não experimentar a senha contra várias contas até alguma aceitar.

### P4 — Limites legados de tipo inválido derrubam a validação da licença

**Tipo:** robustez/disponibilidade, prioridade média; obrigatório verificar dados antes da migração real.

**Local:** `getping_admin/routes/api.py:68` e validações de banco/CLI.

O código compara diretamente valores SQLite com inteiros. Um registro legado com `limite_hosts='invalid'` causou `TypeError`. Em teste com propagação de exceções, a exceção chegou ao chamador; no tratamento normal de produção, resultaria em 500, e não no 503 controlado descrito no README.

As validações de faixa atuais não explicitam que os valores precisam ser inteiros; dados históricos e edições externas exigem cuidado adicional. O ensaio inseriu inconsistência deliberadamente em banco temporário, após remover o trigger de update; não demonstra presença desse dado no banco operacional.

**Correção:** validar tipo/faixa de forma controlada no serviço, fortalecer constraints/triggers para números inteiros e revisar legados sem inventar valores comerciais. Executar `check-data` em cópia e no procedimento de atualização. Acrescentar casos de texto, nulo e número fracionário.

### P5 — Diagnóstico estrito pode aprovar estrutura incompleta e dado inválido

**Tipo:** confiabilidade operacional, prioridade média.

**Locais:** `getping_admin/commands.py:125` e health em `getping_admin/__init__.py`.

Em fixture com HTTPS/fingerprint configurados, licença vinculada, `limite_hosts=-1` e trigger de update removido:

```text
security-check --strict: exit 0
/health: HTTP 200
check-data: exit 1
```

O diagnóstico valida integridade SQLite/referências e versões, mas não incorpora `check-data` nem confere todos os objetos esperados das migrações. O registro da versão não garante a existência dos triggers. `init-db` também não reaplica automaticamente uma migração já registrada.

**Correção:** diagnóstico profundo que verifique dados e objetos esperados, com mensagem clara de drift. Manter health leve é aceitável; documentar exatamente o que ele prova e usar o diagnóstico completo na liberação. Não reparar schemas desconhecidos silenciosamente.

### P6 — Conferir a correção do SQLite para o problema WAL-reset

**Tipo:** dependência de sistema com possível impacto em integridade; revisão necessária antes da produção.

O Python local usa SQLite **3.45.1**. O projeto habilita WAL e prevê múltiplos workers/threads. A documentação oficial descreve um [bug raro de WAL-reset](https://www.sqlite.org/wal.html#walreset) capaz de corromper o banco sob concorrência. A correção está em 3.51.3 ou posterior, com backports upstream específicos. O número local está no intervalo upstream afetado; não foi verificado se o fornecedor do sistema aplicou patch mantendo a versão base.

**Ação:** confirmar o patch no pacote usado pelo Python da VPS ou adotar runtime corrigido. Não basta atualizar pacotes via pip ou verificar somente o executável `sqlite3`. Não foi reproduzida corrupção nesta revisão.

```bash
venv/bin/python -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

## Melhorias e riscos operacionais restantes

### Escritas por validação e capacidade

`limits.py:14` abre uma transação de escrita para cada orçamento verificado, mesmo quando a requisição já excedeu a cota. Uma chamada normal da API pode escrever para IP, chave e check-in, em transações separadas. A limpeza por janela ainda roda em cada orçamento. O índice introduzido na migração 002 melhora a limpeza, mas não elimina a disputa pelo escritor.

WAL permite concorrência entre leitores e escritor, mas mantém um escritor por vez; o banco deve ficar em disco local no mesmo host. São restrições documentadas pelo [SQLite](https://www.sqlite.org/wal.html). Não foi demonstrada saturação nesta análise.

Antes de atender carga real, medir latências p95/p99, erros 429/503 e espera por locks com a frequência de check-in esperada, incluindo clientes atrás de um mesmo NAT. A cota padrão de 120/minuto por IP é compartilhada por todas as instalações daquele IP. Testar junto com backup e retenção. Aplicar limites também no Nginx para que tráfego rejeitado não precise sempre chegar ao SQLite. Redis para o limitador ou PostgreSQL para os dados são alternativas se medições justificarem.

Não há base para recomendar tamanho comercial de VPS ou prometer número de clientes. Estimar primeiro `instalações / intervalo de check-in`, contemplar picos/retries, e medir na infraestrutura candidata. Aumentar workers isoladamente não remove a serialização das escritas.

### Auditoria e detecção

- Login/logout bem-sucedidos são auditados. Credencial inválida e bloqueio por limite não têm evento persistente próprio; senha errada pode responder 200 com formulário, dificultando identificação só pelo access log.
- Exclusão de cliente inexistente (`routes/clientes.py:211`) grava `delete` e aparenta sucesso: POST autenticado para ID inexistente retornou 302 e gerou um evento. Verificar existência/`rowcount` e auditar somente a alteração efetiva.
- Definir retenção da auditoria administrativa e do journal. `prune-logs` preserva `admin_audit`, que cresce sem limite próprio.
- Criar eventos de falha agregados e alertas sem senha, cookies, tokens ou chave integral. Evitar inundação de logs pelo próprio ataque.

### Licenciamento e cliente

Licenças novas aguardam autorização do superadmin, mesmo com o modo global de compatibilidade. Licenças antigas sem binding continuam em compatibilidade até transição. A migração 002 precisa ser aplicada antes de servir a versão atual.

Fingerprint é uma identidade declarada e copiável. A comparação atual não garante exclusividade física da instalação. Hosts/agentes, cache offline, comportamento em queda da API, retries e validação TLS precisam de avaliação no cliente GetPing, cujo código não faz parte deste escopo. Uma falha da VPS não deveria produzir efeitos comerciais inesperados por uma política de tolerância indefinida.

Antes de `GETPING_REQUIRE_FINGERPRINT=1`, conferir e autorizar cada instalação legítima. Não preencher autorizações automaticamente com fingerprints históricos. O formato legado das chaves tem 64 bits aleatórios; o formato opcional estendido tem 128 bits. Habilitar o formato novo somente após testar compatibilidade do cliente.

### Permissões, backups e recuperação

O banco local está com modo `0644`, em diretório `0755`. O acesso efetivo depende também dos diretórios ancestrais e ACLs; isso não comprova vazamento. Em produção, proteger diretório operacional, banco/WAL/SHM, segredo e backups. O `UMask=0077` dos exemplos systemd ajuda os arquivos novos, mas comandos manuais precisam da mesma disciplina e arquivos existentes não são corrigidos automaticamente.

Há comando de backup e roteiro de restauração, mas não há rotina de backup externo agendada nos artefatos de deploy examinados. Definir frequência de acordo com a perda de dados aceitável, retenção, cópia fora da VPS, proteção do armazenamento, alerta de falha e teste de recuperação em outro diretório/servidor. Não copiar apenas o `.db` de um banco ativo como estratégia de backup.

Manter rollback com código, dependências e banco compatíveis. Restauração do banco remove operações posteriores ao backup. Não tratar uma única VPS como alta disponibilidade; definir o tempo de recuperação aceitável para o serviço de licenças.

### Qualidade, documentação e dependências

O CI existente cobre boas verificações, mas falta auditoria automatizada de dependências. `pip check` verifica compatibilidade, não vulnerabilidades. O runtime SQLite exige acompanhamento fora do requirements. O [aviso oficial do Werkzeug](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m) consultado identifica 3.1.9 como corrigida para aquele problema específico; não constitui auditoria completa de todas as dependências.

Revalidar uma instalação limpa com `requirements-production.txt`, CI e wheel do estado exato a publicar. Há arquivos modificados e ainda não rastreados no workspace, incluindo migração 002, testes e relatórios; garantir que a release inclua todos os artefatos necessários. Um clone do último commit pode diferir do código analisado.

No frontend, o plano Básico inicia com dez hosts, mas selecionar Básico no JavaScript sugere quinze (`static/js/licencas.js:16`). Centralizar os defaults e esclarecer se limites personalizados são intencionais. Editar validade normaliza para o fim do dia UTC; confirmar que alterar outro campo não deve modificar horários legados. A dependência externa de ícones é uma disponibilidade visual adicional, sem necessidade imediata de reestruturação.

MFA administrativo e reautenticação nas operações mais sensíveis são melhorias recomendáveis para exposição pública. A ausência dessas camadas não foi demonstrada como bypass nesta revisão.

## Critérios concretos para liberar

1. Corrigir P2–P5 e adicionar regressões pertinentes; confirmar P6 no runtime candidato.
2. Fixar a release completa, executar CI e validar instalação limpa/wheel com dependências de produção.
3. Em homologação, ensaiar backup/restauração e aplicar migrações em cópia representativa; exigir `check-data` válido e diagnóstico aprofundado sem inconsistências.
4. Configurar P1, usuário de serviço, diretório restrito, segredo estável, certificado e renovação. Ajustar `ReadWritePaths` dos serviços ao diretório real do banco.
5. Testar do cliente real: login/troca de senha, permissões dos três perfis, emissão, autorização e transferência de instalação, validação, expiração, suspensão e comportamento durante indisponibilidade.
6. Testar carga de check-in e picos esperados, NAT, excesso de cota, migração/backup e retenção sem degradação inaceitável.
7. Habilitar backup externo, timer de retenção, monitor HTTPS/health, alertas de 5xx/429, disco/WAL e falhas do serviço; documentar recuperação.

**Decisão:** homologação pode começar. Produção deve aguardar as correções comprovadas e o aceite da configuração/recuperação na VPS. O caminho é finalizar a robustez e a operação da base existente.
