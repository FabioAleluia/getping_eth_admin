# Preparar a central e instaladores simples dos clientes

**Atualização:** a partir do GetPing 1.1.4, compilar e instalar não exige perfil da central. O cliente executa `sudo ./install.sh` e configura/ativa depois pela interface. A preparação descrita abaixo é opcional e destinada à administração da central; não é um pré-requisito da instalação.

A preparação é feita uma vez pelo administrador/fornecedor na central. O cliente
recebe somente o pacote GetPing e executa `sudo ./install.sh`. A central pode
continuar na rede local: não é necessário publicar na nuvem.

## 1. Preservar a assinatura em uso

Localize a chave privada já usada em `GETPING_LICENSE_SIGNING_KEY_FILE`, na
configuração da central. Não gere outro par para uma central que já assina
licenças. Os comandos abaixo usam `/caminho/chave-assinatura-existente.pem` como
exemplo: substitua pelo caminho real. Nenhum deles altera essa chave ou o banco.

Somente se a central ainda NÃO possuir um par de assinatura, o comando existente
`venv/bin/python -m getping_admin.license_keys --private CAMINHO_PRIVADO --public CAMINHO_PUBLICO`
permite criá-lo explicitamente; proteja a privada com 0600 e configure sua leitura
pelo usuário do serviço. Essa criação não é feita silenciosamente pelo assistente.

## 2. Preparar HTTPS local

Na pasta do projeto GetPing Adm:

```bash
venv/bin/python -m getping_admin.prepare_local_https \
  --url https://192.168.10.108 \
  --signing-key /caminho/chave-assinatura-existente.pem \
  --output /diretorio-protegido/preparacao-central
```

Use o IP/DNS real da central. O diretório de saída deve ser novo. São criados:
certificado de CA local, chave privada dessa CA, certificado HTTPS com SAN do IP
ou DNS, chave TLS, configuração Nginx, fragmento de variáveis e `client-profile/`.
A chave de assinatura existente é somente lida para derivar sua parte pública.
Nenhum serviço, configuração operacional ou banco é alterado pelo comando.

Preserve a pasta protegida e suas chaves. O comando recusa sobrescrever uma
preparação existente, evitando rotacionar a CA e invalidar clientes sem querer.
O certificado HTTPS vale um ano; planeje sua renovação antes de expirar,
reutilizando a mesma CA. A CA vale dez anos. Esta ferramenta não agenda renovação.

Se a central já possui HTTPS válido da organização, pule esta geração: use a
exportação da seção 4 com a CA pública da organização, quando necessária.

## 3. Aplicar na VM da central (uma vez)

Revise os arquivos antes de aplicar. Na VM Ubuntu com Nginx instalado:

```bash
sudo install -d -m 0700 /etc/getping-admin/tls
sudo install -m 0644 /diretorio-protegido/preparacao-central/server.crt /etc/getping-admin/tls/server.crt
sudo install -m 0600 /diretorio-protegido/preparacao-central/server.key /etc/getping-admin/tls/server.key
sudo install -m 0644 /diretorio-protegido/preparacao-central/getping-admin.conf /etc/nginx/sites-available/getping-admin.conf
sudo ln -sfn /etc/nginx/sites-available/getping-admin.conf /etc/nginx/sites-enabled/getping-admin.conf
sudo nginx -t
```

A configuração faz proxy para `127.0.0.1:5001`, endereço já usado em
`deploy/gunicorn.conf.py`. O backend deve estar acessível somente localmente.
O exemplo assume porta HTTPS 443 disponível para a central; revise conflitos
com outros sites antes de ativar. Se faltar Nginx, instale-o separadamente.

Mescle os valores de `central.env.fragment` no arquivo de ambiente do serviço
(exemplo: `/etc/getping-admin.env`, conforme `deploy/getping-admin.service.example`).
Mantenha `SECRET_KEY`, `GETPING_DATABASE`, `GETPING_LICENSE_SIGNING_KEY_FILE` e
outras variáveis existentes. Não substitua o arquivo inteiro pelo fragmento.
Use `GETPING_ENV=production` no serviço, preserve o banco e siga a unidade de
produção já documentada. O fragmento configura HTTPS, origem pública, vínculo
obrigatório e confiança em um proxy local.

Depois da revisão/configuração:

```bash
sudo systemctl restart getping-admin
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl --cacert /diretorio-protegido/preparacao-central/ca.crt https://192.168.10.108/health
```

Ajuste o nome do serviço caso sua unidade tenha outro nome. O endpoint de saúde
verifica disponibilidade; o instalador GetPing também validará o protocolo e a
assinatura no endpoint real de licenças. A confiança do navegador do painel pode
exigir instalar somente a CA pública nos computadores administrativos.

## 4. Exportar perfil público

A preparação local já gera `client-profile/`. Para central com HTTPS existente,
ou para exportar novamente sem regenerar certificados:

```bash
venv/bin/python -m getping_admin.client_profile \
  --url https://192.168.10.108 \
  --signing-key /caminho/chave-assinatura-existente.pem \
  --ca-cert /caminho/ca-publica.crt \
  --output /novo/diretorio/client-profile
```

`--ca-cert` é opcional para HTTPS com CA pública já reconhecida. A exportação
contém somente `central.json`, `license-public.pem` e, quando necessário,
`license-ca.crt`. A assinatura é Ed25519 e as raízes TLS são certificados de CA.
**Copie somente essa subpasta**, nunca a preparação completa, a chave privada de
assinatura, `server.key`, `ca-private.pem`, ambiente ou banco.

## 5. Gerar o GetPing uma vez por versão

Transfira o conteúdo de `client-profile/` para `packaging/central/` no projeto
GetPing. Esse diretório não entra no Git. O build valida o perfil antes de compilar
ou empacotar. Arquivos extras da pasta não são copiados para o pacote.

```bash
venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
venv/bin/python scripts/build_release.py --version 1.1.3 --jobs 2
```

Também é possível informar `--central-profile /caminho/client-profile`. Depois
dessa preparação, o comando normal de build funciona sem repetir os dados.

## 6. Instalar no cliente

Transfira e extraia o pacote gerado. O único comando de instalação normal é:

```bash
sudo ./install.sh
```

O IP da VM é detectado. Havendo mais de um IPv4, o instalador pede apenas a escolha
do IP de acesso. URL, chave pública e CA vêm do pacote; configuração existente é
preservada no upgrade. Continua sendo pedida a senha inicial do GetPing se a conta
root ainda não existir. Uma falha na conexão/assinatura da central bloqueia a
instalação com orientação ao administrador, sem pedir arquivos técnicos ao cliente.
