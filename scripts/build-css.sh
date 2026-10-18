#!/bin/sh
set -eu
# Argument: path to the official standalone Tailwind CLI 3.4.17.
# https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17
if [ "$#" -ne 1 ]; then
    echo 'Uso: sh scripts/build-css.sh /caminho/tailwindcss-3.4.17' >&2
    exit 1
fi
"$1" -i assets/tailwind.css -o getping_admin/static/css/tailwind.css --minify
