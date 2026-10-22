# Atualização coordenada: GetPing 1.1.0 e Admin 0.2.0

As correções da análise de 22/10 foram implementadas nos fontes dos dois projetos. A implantação deve ser coordenada: o cliente de produção novo exige autorizações assinadas pela central nova. Não basta atualizar somente o cliente ou reutilizar um executável anterior.

## Regras confirmadas pelo proprietário

- **Zero agentes significa nenhum agente permitido**, inclusive dispositivos cadastrados anteriormente.
- Licença expirada, revogada, de outra instalação ou com tolerância offline vencida **bloqueia coleta e acesso**. Configurações, login e revalidação continuam acessíveis aos perfis autorizados para recuperação. Nenhum histórico existente é apagado.

## Alterações

| Problema | Comportamento novo |
|---|---|
| HTTP em produção | Central e cliente exigem HTTPS; produção não inicia com os requisitos de confiança ausentes. HTTP/servidores simulados são permitidos apenas no modo explícito `development`. |
| Autoridade selecionável | A origem é fixada na configuração operacional do cliente; root da aplicação não troca a central em produção. A URL gravada no SQLite não controla mais o destino da sincronização de produção. |
| Prova de emissão | A central assina documentos Ed25519, e o cliente verifica com uma chave pública configurada fora do banco. A chave privada nunca é distribuída aos clientes. |
| Replay/resposta cruzada | Cada consulta tem nonce aleatório; assinatura vincula requisição, chave, fingerprint, emissor e horários. Respostas repetidas não renovam o check-in. |
| Contrato incompleto | Autorização positiva exige cliente, plano, limites e expiração válidos; negativas seguem uma lista explícita de estados. |
| Transferência de instalação | `instancia_invalida` é negativa autoritativa e bloqueia imediatamente; não usa tolerância de falha de rede. |
| Cache | HMAC v2 usa JSON canônico com domínio próprio e inclui URL, check-in, documento central e revisão. O cliente verifica a identidade atual e a assinatura central. |
| UTC/offline | Emissão, vencimento e prazo offline usam UTC com fuso explícito. A tolerância é comparada por duração exata e limitada pelo prazo assinado pela central. |
| Concorrência | Persistência compara o snapshot anterior à chamada de rede; resposta antiga não altera ativação/revalidação posterior. Nenhum lock de banco fica aberto aguardando rede. |
| Coleta | O recebimento de agentes e a persistência de sondas verificam a licença. Zero agentes bloqueia todos; redução da cota bloqueia os excedentes por ordem de cadastro. O coletor cancela/aguarda tarefas em andamento e descarta resultados após bloqueio. |
| Login | Removido o bloqueio global por conta no GetPing; limites por origem e par origem/usuário permanecem. |
| Qualidade | Testes de assinatura, produção e integração entre os projetos; formatação corrigida, dependências de runtime fixadas e pip local atualizado. |

O heartbeat de serviço continua ativo enquanto o coletor aguarda uma licença válida. `/status_server` informa separadamente `coleta_autorizada` e `status_licenca`; readiness do processo não é aprovação comercial da licença.

## Preparação das chaves

Execute na máquina de preparação/central com as dependências novas instaladas, em diretório protegido existente:

```bash
venv/bin/python -m getping_admin.license_keys \
  --private /CAMINHO-PROTEGIDO/license-private.pem \
  --public /CAMINHO-PROTEGIDO/license-public.pem
```

O comando não sobrescreve arquivos. A chave privada é criada com modo 0600. Preserve-a de forma protegida, com cópia de recuperação; **não gere outra chave a cada reinício/atualização**. A chave pública pode ser distribuída por canal administrativo confiável. Confirme sua autenticidade antes de instalar no cliente. Não aceite a chave pública recebida do endpoint que ela deveria autenticar.

Em produção, o serviço central precisa ler a chave privada, mantendo modo 0600 e propriedade adequada ao usuário do serviço. O cliente precisa apenas da pública, idealmente sob propriedade de root e sem escrita pelo usuário web/monitor. A geração não foi executada em caminhos operacionais nesta tarefa.

## Configuração de produção da central

```ini
SECRET_KEY=SEGREDO-DE-SESSAO-ALEATORIO-PERSISTENTE
GETPING_ENV=production
GETPING_DATABASE=/CAMINHO-REAL/db_getping.db
GETPING_PUBLIC_BASE_URL=https://SEU-DOMINIO-REAL
GETPING_REQUIRE_HTTPS=1
GETPING_REQUIRE_FINGERPRINT=1
GETPING_LICENSE_SIGNING_KEY_FILE=/etc/getping-admin/license-private.pem
GETPING_PROXY_HOPS=1
```

`GETPING_PROXY_HOPS=1` pressupõe exatamente o proxy confiável previsto no exemplo Nginx, que sobrescreve os cabeçalhos e é o único acesso ao backend em loopback. Ajuste para a topologia real. Configure certificado válido e renovação.

## Configuração de produção do cliente

No `/etc/getping/getping.env` da instalação empacotada, ou ambiente equivalente dos fontes:

```ini
GETPING_ENV=production
LICENCA_SERVER_URL=https://SEU-DOMINIO-REAL
LICENCA_PUBLIC_KEY_FILE=/etc/getping/license-public.pem
SESSION_COOKIE_SECURE=1
```

A URL deve coincidir com a origem configurada na central. Não use caminho, credenciais ou query string. Para uma CA TLS privada, configure também `REQUESTS_CA_BUNDLE` com o certificado público da CA; nunca desabilite a validação TLS. Essa CA é diferente da chave pública Ed25519 de licenciamento.

O template de configuração contém uma origem `.invalid` deliberadamente não operacional; substitua-a. Instale a chave pública e prepare o arquivo de configuração **antes** de executar o instalador/atualizador. O instalador agora executa `check-config` antes de parar serviços ou migrar dados. Para conferir manualmente:

```bash
getping check-config
```

Nos fontes, use `python -m getping check-config`. O comando valida a configuração sem criar/migrar tabelas. O uso local por HTTP exige escolha explícita de `GETPING_ENV=development`; não use esse modo na VPS/instalação de produção.

## Ordem da atualização

1. Preserve código/binários, configuração e backups consistentes dos dois sistemas; ensaie a atualização e a restauração em cópias.
2. Instale as dependências declaradas e prepare o par Ed25519. Nenhuma chave operacional foi gerada automaticamente.
3. Configure HTTPS e emissão na central; autorize os fingerprints legítimos antes de exigir o vínculo global. Confira a aplicação das migrações 001–003 do Admin, dados e diagnóstico.
4. Atualize a central para 0.2.0. Ela mantém campos do contrato anterior e acrescenta a autorização assinada; um cliente antigo não obtém as proteções novas até ser atualizado.
5. Prepare a configuração/chave pública do GetPing. Faça backup do estado, incluindo segredo e `.server_fingerprint`. Atualize o pacote/binário para 1.1.0.
6. Execute `init-db` explicitamente para acrescentar `autorizacao_json` e `revision` em `licenca_local`. A migração não reemite licenças nem assina o cache antigo como se ele tivesse vindo da central.
7. **Revalide online.** Um cache antigo é recusado até receber nova autorização válida. Preserve o segredo e o fingerprint existentes; não apague o banco para resolver a transição.
8. Teste licença válida, zero agentes, suspensão, cancelamento, transferência, vencimento, falha de rede, coleta bloqueada e recuperação na instalação real.

Se executar os fontes, instale os requirements novos de cada projeto no seu próprio venv. Atualizar dependências no computador de desenvolvimento não atualiza automaticamente um executável Nuitka instalado na VM: compile/distribua a nova versão. As configurações de empacotamento agora incluem o suporte criptográfico.

## Recuperação e limites operacionais

- Mantenha backup consistente dos bancos e cópias protegidas de configuração, segredo de sessão, fingerprint e chave privada da central. Ensaiar restauração é obrigatório antes de uso comercial.
- Não restaure apenas um `.db` enquanto o serviço escreve WAL. O retorno ao código anterior exige banco/configuração compatíveis e perde operações posteriores ao backup restaurado.
- Trocar a chave de emissão exige uma transição planejada da chave pública nos clientes e revalidação. Esta versão usa uma chave pública configurada por instalação; não há rotação automática com múltiplas chaves.
- Quem controla completamente o SO pode alterar executável/configuração e copiar identidades. Assinatura central melhora a fronteira de confiança do protocolo/cache; não transforma um cliente administrável pelo destinatário em hardware inviolável.
- Confirmar no runtime da VPS o patch de WAL-reset do SQLite, além de certificados, firewall, backups externos, alertas e capacidade. Não foi atualizada a biblioteca SQLite do sistema nem alterado serviço na VPS nesta tarefa.

## Verificação

Os resultados finais e os comandos de validação ficam no diretório `docs/evidencias_correcoes_integracao_2026-10-22/` do Admin. A integração é executada explicitamente com os dois checkouts; o CI independente de cada projeto executa os seus testes próprios sem depender de um repositório irmão ausente.
