# Para iniciar agora a aplicação exige uma SECRET_KEY segura
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export GETPING_ENV=development


# Para criar a senha do "administrator"
python3 -m flask --app app:create_app reset-password administrator


# Outros
python3 -m flask --app app:create_app backup-db /tmp/getping-antes-migracao.db
python3 -m flask --app app:create_app init-db

python3 app.py

