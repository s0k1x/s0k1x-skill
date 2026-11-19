#!/bin/sh
# SessionStart: inyecta s0k1x-maestra en el contexto de cada sesión
# (inicio, resume, /clear y /compact). Desactívala con S0K1X_MAESTRA=off.
[ "${S0K1X_MAESTRA:-on}" = "off" ] && exit 0
DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
[ -f "$DIR/SKILL.md" ] || exit 0
echo "s0k1x-maestra ACTIVE: follow these rules every reply until \"modo normal\". Already loaded; do not call the Skill tool for it."
echo
awk 'NR==1 && /^---$/ {f=1; next} f && /^---$/ {f=0; next} !f' "$DIR/SKILL.md"
