> **Atualização de segurança 0.2.0 / protocolo 2:** produção agora exige HTTPS,
> vínculos autorizados e chave privada Ed25519. HTTP e respostas sem assinatura
> são permitidos apenas no modo explícito de desenvolvimento. Leia
> [o roteiro de atualização coordenada](docs/CORRECOES_INTEGRACAO_2026-10-22.md)
> antes de usar os procedimentos históricos abaixo.

# GetPing Admin

Painel Flask/SQLite para clientes, usuários e licenças do GetPing. Python 3.12.

## Instalação local

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export GETPING_ENV=development
flask --app getping_admin:create_app init-db
flask --app getping_admin:create_app create-admin
python -m getping_admin
```

Acesse `http://127.0.0.1:5001`. `create-admin` solicita e-mail e senha sem exibi-la; o primeiro login exige troca. Não existe senha administrativa universal. Guarde a chave secreta em local protegido e reutilize-a nos reinícios; gerar uma nova encerra as sessões existentes.

A aplicação exige `SECRET_KEY` com pelo menos 32 caracteres e rejeita a chave antiga conhecida. O arquivo `.env.example` descreve as variáveis; **`python -m getping_admin` não carrega `.env` automaticamente**. Exporte as variáveis no processo ou configure o serviço. Não versionar segredos.

Novas instalações usam `instance/db_getping.db`. Se o banco legado `database/db_getping.db` existir ao lado do pacote, ele continua sendo utilizado, sem mover dados. `GETPING_DATABASE` tem precedência e deve apontar explicitamente para o banco operacional na implantação. A importação de `getping_admin` e a factory não aplicam migrações nem criam contas. Use `init-db` explicitamente antes de iniciar uma instalação nova ou atualizada.

O código está em `getping_admin/`, os testes em `tests/` e os relatórios anteriores em `docs/historico/`. Consulte [o guia de desenvolvimento](docs/desenvolvimento.md) para a estrutura, instalação do pacote e verificações. `python app.py` e `app:create_app` continuam disponíveis como entradas de compatibilidade.

## Atualização de uma instalação existente

1. Interrompa o serviço para a atualização; preserve a versão anterior do código e sua configuração.
2. Configure o ambiente com a nova chave segura e o caminho correto do banco. Não gere uma chave a cada início do serviço.
3. Faça backup consistente e copie-o para armazenamento protegido:

   ```bash
   flask --app getping_admin:create_app backup-db /caminho/seguro/getping-antes-atualizacao.db
   ```

4. Teste a restauração e as migrações em uma cópia, apontando `GETPING_DATABASE` para ela.
5. No banco operacional, execute:

   ```bash
   flask --app getping_admin:create_app init-db
   flask --app getping_admin:create_app check-data
   ```

6. Se a conta ainda usa a senha antiga `administrator`, recupere-a localmente:

   ```bash
   flask --app getping_admin:create_app reset-password administrator
   ```

7. Inicie o serviço e verifique `/health`, login, clientes, emissão e validação de uma licença de teste.

As migrações preservam contas, hashes e licenças. Não corrigem silenciosamente limites ou datas inválidos existentes: `check-data` informa os IDs para revisão. Uma licença inconsistente é negada pela API com 503, sem expor detalhes internos. Alterações futuras passam pelas novas validações e constraints.

A senha antiga universal não é mais aceita, mesmo quando seu hash ainda está no banco. A atualização invalida sessões antigas sem versão de autenticação. Reset de senha e alterações administrativas da conta revogam suas sessões; mudança de senha pelo perfil mantém apenas a sessão atual.

**Retorno à versão anterior:** pare o serviço, restaure código, dependências e banco do backup compatível. Não sobrescreva somente o `.db` de um SQLite ativo: o WAL pode conter transações. Faça a restauração com o serviço parado, valide o backup e retire os arquivos WAL/SHM da versão substituída conforme procedimento operacional. Operações realizadas após o backup não estarão na restauração.

## Produção

**Atualização de código de 21/10/2026:** esta versão também exige a migração
`003_production_validation.sql`. Consulte o [roteiro e as correções](docs/CORRECOES_CODIGO_2026-10-21.md)
antes de atualizar. A migração verifica conflitos entre identificadores, normaliza
contas sem conflito e fortalece a validação dos limites. Não corrige valores
comerciais inválidos automaticamente. O diagnóstico de produção agora verifica
dados e objetos esperados; `/health` verifica a estrutura sem varrer dados comerciais.

```bash
pip install -r requirements-production.txt
export GETPING_ENV=production
# Configure SECRET_KEY persistente, GETPING_DATABASE e demais variáveis no serviço.
gunicorn -c deploy/gunicorn.conf.py 'getping_admin:create_app()'
```

O backend escuta apenas em `127.0.0.1:5001`; publique por proxy HTTPS. Há exemplos em `deploy/nginx.conf.example` e `deploy/getping-admin.service.example`. Substitua usuário, caminhos, domínio e certificados antes de instalar os arquivos. Não utilize `flask run`, debug ou `python -m getping_admin` como servidor de produção.

Em produção, o cookie exige HTTPS. Configure `GETPING_PROXY_HOPS=1` somente atrás de um proxy confiável que sobrescreva os cabeçalhos encaminhados, sem acesso externo direto ao backend. O exemplo Nginx faz isso. Com zero saltos, `X-Forwarded-For` é ignorado. Mais de um proxy exige configuração específica para sua topologia.

A aplicação envia CSP, proteção contra enquadramento, `nosniff`, `no-store`, política de referência e HSTS para respostas HTTPS de produção. Scripts são locais; Font Awesome continua sendo uma folha de estilo e fontes externas de versão fixa. Falha nesse CDN afeta ícones, não autenticação ou validação.

`/health` verifica acesso à estrutura esperada do banco e responde 503 em falha. Configure o monitor externo para consultar essa rota, acompanhar erros 5xx/429, tempo de validação, espaço em disco e falhas do serviço. Logs de requisição e erros do Gunicorn vão para stdout/stderr; o exemplo systemd os envia ao journal. Não registre corpos da API: contêm chaves de licença.

## Licenciamento e compatibilidade

```http
POST /api/v1/licenca/validar
Content-Type: application/json

{"chave_licenca":"GPING-...","fingerprint":"ID-DA-INSTALACAO","versao":"0.0.4"}
```

A resposta mantém os campos anteriores e acrescenta `expira_em_iso`, com UTC explícito. Datas existentes continuam em UTC; editar validade usa o fim do dia UTC, informado no formulário. Não houve mudança silenciosa para horário de São Paulo.

- `GETPING_REQUIRE_FINGERPRINT=0` preserva compatibilidade somente para licenças antigas ainda não autorizadas. Licenças novas e licenças autorizadas explicitamente já exigem vínculo, mesmo com essa variável em zero.
- `GETPING_REQUIRE_FINGERPRINT=1` exige vínculo autorizado em todas as licenças. A API não autoriza a primeira instalação automaticamente. Uma licença sem autorização retorna 403 (`aguardando_vinculo`), mesmo que exista um fingerprint observado historicamente.
- Antes de ativar o modo obrigatório, verifique o cliente GetPing e os fingerprints já gravados. Eles podem refletir o primeiro uso histórico, sem representar a instalação atualmente legítima.
- Nos detalhes, o superadmin informa o fingerprint confirmado no GetPing e sua própria senha atual em **Autorizar instalação e exigir vínculo**. A ação é auditada e afeta aquela licença. **Liberar instalação vinculada** remove a autorização e mantém a exigência: nenhuma máquina consegue reivindicar o vínculo até nova autorização explícita. Para transferir diretamente, autorize o novo fingerprint; o anterior será rejeitado.
- Um fingerprint enviado pelo cliente pode ser copiado. Ele não prova posse de hardware. Credencial por instalação, assinatura de autorização offline e enforcement de hosts/agentes exigem implementação e testes também no cliente GetPing.

JSON inválido e campos fora dos limites retornam 400; licença inexistente, 404; bloqueada/expirada, 403; excesso de requisições, 429 com `Retry-After`; indisponibilidade/inconsistência, 503. Erros da API usam JSON com `valido=false` e `motivo`.

O formato de chave antigo é preservado por padrão. `GETPING_EXTENDED_KEYS=1` permite gerar chaves com 128 bits aleatórios, mais longas, após verificar o formato aceito pelo cliente. Chaves antigas continuam válidas sem regeneração. O status efetivo considera situação do cliente, status da licença e instante de expiração em API, listagens, detalhes e indicadores.

## Permissões

| Ação | Superadmin | Gestor | Assistente |
|---|---|---|---|
| Consultar clientes e licenças | Sim | Sim | Sim |
| Criar cliente e emitir licença | Sim | Sim | Não |
| Alterar condições de licença | Sim | Sim | Não por padrão |
| Atualizar contatos e notas internas do cliente | Sim | Sim | Sim |
| Alterar outros dados/excluir cliente sem licença | Sim | Sim | Não |
| Excluir licença, usuário ou liberar instalação | Sim | Não | Não |
| Criar usuário | Gestor/assistente | Assistente | Não |
| Editar usuário | Contas permitidas | Assistentes e própria conta, sem mudar papéis | Próprio perfil |

O usuário `administrator` continua protegido contra exclusão, desativação e rebaixamento. Alterar o próprio papel é bloqueado. Caso a operação exija manter a autorização comercial antiga para assistentes, `ALLOW_ASSISTANT_LICENSE_EDITS=True` pode ser fornecido explicitamente à factory pela configuração da implantação; não é o padrão.

## Auditoria, limites e retenção

`admin_audit` registra operador, ação, alvo, alterações, IP e horário na transação da mudança. Senhas, hashes e chaves completas não são incluídos. A recuperação local por CLI aparece com operador nulo e ação específica. A tabela contém dados pessoais: restrinja permissões do banco e dos backups.

Por padrão, login permite 10 requisições por IP/minuto. Depois de CSRF e validação dos campos, há orçamento por identificador/origem; não existe bloqueio global por conta que outra origem possa esgotar. API permite 120 requisições por IP/minuto e 600 por chave/minuto. As janelas são fixas e compartilhadas entre workers por SQLite. Clientes atrás do mesmo NAT compartilham a cota de IP: ajuste `API_RATE_LIMIT`, `LOGIN_RATE_LIMIT` e `RATE_WINDOW_SECONDS` na configuração da factory conforme a carga legítima. Os limites são defesa de aplicação; proteção contra tráfego volumétrico pertence também ao proxy/infraestrutura.

Payloads têm limite de 32 KiB. Validações de chaves desconhecidas não criam eventos no banco. Check-ins bem-sucedidos são agregados em até um evento por licença/hora; falhas podem ser acompanhadas pelos códigos HTTP do servidor. O último check-in continua sendo atualizado. Não há log por chamada bloqueada, evitando crescimento causado por abuso.

Agende diariamente, com o mesmo ambiente do serviço:

```bash
flask --app getping_admin:create_app prune-logs
```

Remove logs de validação anteriores a 90 dias e contadores expirados. Não apaga a auditoria administrativa. Defina a retenção dessa auditoria segundo a política da operação e o espaço disponível. A exclusão de linhas não reduz automaticamente o arquivo SQLite; manutenção/compactação deve ser planejada separadamente. Proteja o diretório do banco com permissões restritas; SQLite precisa escrever nele para criar WAL/SHM.

## Testes

```bash
python -B -m unittest discover -v
```

Cada teste tem banco e contexto temporários próprios, configurados antes de qualquer inicialização. A factory rejeita `TESTING=True` com banco fora do diretório temporário do sistema. Nenhum teste usa o banco operacional. A suíte cobre os fluxos anteriores e regressões de permissões, sessão, senha, API, validação de campos, rate limiting, auditoria, migrações e concorrência na ativação.

## CSS e dependências

O CSS compilado está versionado em `getping_admin/static/css/tailwind.css`; Node e compilador não são necessários no servidor. Para alterar as classes, gere-o novamente com o CLI standalone oficial Tailwind **3.4.17**:

```bash
sh scripts/build-css.sh /caminho/tailwindcss-3.4.17
```

Configuração: `tailwind.config.js`; entrada: `assets/tailwind.css`; saída: `getping_admin/static/css/tailwind.css`. Scripts inline e handlers HTML foram substituídos por arquivos JS e atributos de dados para compatibilidade com CSP.

As dependências diretas e ferramentas estão em `pyproject.toml`; os arquivos `requirements*.txt` fixam também as dependências transitivas para implantação. Atualize ambos em conjunto e valide a instalação. Gunicorn é opcional em produção. Atualizações devem passar por revisão, auditoria de dependências e testes; fixar versões não substitui esse acompanhamento.

## Segunda etapa de segurança

O painel agora encerra a sessão após **30 minutos sem atividade** ou **24 horas desde o login**, mesmo com atividade contínua. Arquivos estáticos e chamadas da API de licenças não renovam a atividade do painel. Sessões anteriores a esta etapa, sem os novos marcadores de tempo, exigem novo login. Esses limites não alteram a validade das licenças nem o funcionamento do GetPing na outra máquina.

Em **Meu Perfil**, o botão **Sair de todos os dispositivos** revoga todas as sessões da conta, incluindo a atual e cookies antigos. O logout comum continua encerrando a sessão no navegador atual; não é um mecanismo para revogar cópias de cookies. Em suspeita de roubo de sessão, use a revogação global ou altere a senha.

A edição administrativa da própria conta redireciona para o perfil. POST direto nessa edição é negado; assim, trocar a própria senha exige a senha atual no fluxo do perfil. A redefinição de senha de outras contas segue as permissões administrativas existentes.

O menu **Auditoria**, disponível apenas para superadmin, permite consultar eventos, filtrar ação/entidade/ID do operador e navegar em páginas de 50 registros. Entradas e saídas do painel também são registradas, com o operador identificado. A consulta é somente leitura e não disponibiliza exclusão de eventos.

Antes de publicar ou ativar o vínculo obrigatório, execute com o mesmo ambiente da aplicação:

```bash
flask --app getping_admin:create_app security-check
# Opcional: retorna código de erro quando há recomendações pendentes.
flask --app getping_admin:create_app security-check --strict
```

O diagnóstico verifica integridade/referências e estrutura esperada do banco, informa licenças ativas sem vínculo explicitamente autorizado e sinaliza configuração de desenvolvimento, cookie sem Secure, conta ativa com senha antiga proibida e modo de compatibilidade. Não mostra chaves, senhas ou hashes, não modifica registros e não ativa o bloqueio por fingerprint. Não certifica TLS, firewall ou o comportamento do cliente; esses pontos exigem teste na implantação.

Há exemplos de serviço e timer diário em `deploy/getping-prune-logs.service.example` e `deploy/getping-prune-logs.timer.example`. Depois de ajustar caminhos/usuário/ambiente e instalar os arquivos com nomes sem `.example`, valide-os no servidor e habilite o timer com `systemctl enable --now getping-prune-logs.timer`. Os exemplos não foram instalados automaticamente. A execução preserva auditoria administrativa e remove somente logs de validação antigos/contadores expirados.

Para o teste entre máquinas, `python -m getping_admin` permanece escutando em **0.0.0.0:5001**, com debug desligado, conforme configuração de rede validada. No outro GetPing, use o IP da máquina do Admin, não `localhost`. Essa execução serve aos testes da rede; a configuração de produção continua sendo Gunicorn atrás do proxy HTTPS descrito acima.


## Atualização dos achados altos — 20/10/2026

Esta atualização exige a migração **002_authorized_bindings.sql**. Ela cria a tabela de autorizações sem preencher vínculos com fingerprints históricos e sem alterar planos, limites ou vencimentos. Antes de iniciar a versão nova no banco existente:

```bash
# Use o mesmo SECRET_KEY e GETPING_DATABASE da instalação; pare o serviço para atualizar.
flask --app getping_admin:create_app backup-db /caminho/seguro/getping-antes-20261020.db
flask --app getping_admin:create_app init-db
flask --app getping_admin:create_app check-data
flask --app getping_admin:create_app security-check
```

Preserve uma cópia do código anterior e ensaie restauração/migração em uma cópia do banco. O banco operacional não foi migrado automaticamente durante o desenvolvimento. Mantenha a mesma chave secreta; o reparo da migração preserva `auth_version`, hashes e revogações anteriores. Schemas legados não reconhecidos podem exigir revisão manual em vez de descarte silencioso de colunas.

**Licenças novas exigem autorização pelo superadmin antes da primeira validação.** Licenças antigas permanecem em compatibilidade até autorização individual, a menos que o modo obrigatório global seja ativado. Um gestor pode emitir licença, mas precisa solicitar ao superadmin a autorização da instalação.

### Ativação HTTPS coordenada

1. Defina o domínio/IP do serviço e configure certificado válido para esse endereço no proxy. Certificado de domínio não valida automaticamente acesso pelo IP.
2. Inicie o backend Gunicorn em loopback e configure o proxy conforme `deploy/nginx.conf.example`. Impedir acesso externo direto à porta 5001 é configuração do firewall/rede, não algo que o código pode garantir.
3. Teste do computador GetPing a URL HTTPS com verificação de certificado. Para CA privada, configure a confiança nessa CA no cliente; não desative a verificação TLS.
4. Com o proxy funcionando e sem acesso externo direto ao backend, configure no ambiente de produção:

   ```bash
   GETPING_ENV=production
   GETPING_PROXY_HOPS=1
   GETPING_PUBLIC_BASE_URL=https://admin.exemplo.com
   GETPING_REQUIRE_HTTPS=1
   ```

5. Reinicie o serviço e atualize a URL do servidor central no GetPing para a origem HTTPS. Verifique health, login e validação de licença pela outra máquina.

Quando ativado, o controle HTTPS rejeita HTTP na API e POSTs do painel com **426**, em vez de redirecionar silenciosamente uma validação. GET/HEAD do painel redirecionam com 308 para a origem HTTPS fixa, sem confiar no Host recebido. Health continua disponível no backend para monitor interno. Uma requisição que já saiu do cliente por HTTP já expôs seu conteúdo: o bloqueio no servidor não substitui configurar a URL HTTPS no cliente.

`GETPING_REQUIRE_HTTPS=0` permanece como transição/teste de rede; sua presença não significa que a pendência de HTTPS esteja encerrada. Configure domínio, certificado e rede antes de habilitar. O diagnóstico estrito sinaliza quando essa proteção não está ativada.

### Antes de exigir vínculo global

Autorize os fingerprints conferidos no cliente, teste cada instalação e confirme que nenhuma licença ativa ficou sem autorização. Somente então configure `GETPING_REQUIRE_FINGERPRINT=1`. Fingerprint histórico não é prova de propriedade. A comparação de fingerprint impede divergências informadas, mas não impede cópia da própria identidade; prova criptográfica por instalação continua exigindo alteração no cliente GetPing.

A proteção de login agora evita bloqueio global dirigido por terceiros. A limitação por IP continua ativa antes da análise de CSRF. Isso não substitui mitigação de ataques distribuídos na borda nem MFA; não foi introduzida espera bloqueante nos workers.
