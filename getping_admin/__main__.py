"""Execução local do painel para testes na rede."""

from getping_admin import create_app


def main():
    create_app().run(host="0.0.0.0", port=5001, debug=False)


if __name__ == "__main__":
    main()
