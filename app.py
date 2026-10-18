"""Entrada de compatibilidade; prefira python -m getping_admin."""

from getping_admin import create_app
from getping_admin.__main__ import main

__all__ = ["create_app"]

if __name__ == "__main__":
    main()
