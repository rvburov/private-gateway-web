#!/bin/sh
# Неудачные входы с подмененным X-Forwarded-For: печатает коды ответов через пробел.
#   login-probe.sh <origin> <попыток> [опции curl]
# Нужен для проверки, что лимит попыток считается по настоящему IP посетителя за двумя Caddy
set -eu
base="$1"; n="$2"; shift 2
jar="$(mktemp)"; codes=""
token="$(curl -s -k "$@" -c "$jar" "$base/api/auth/csrf" | sed -n 's/.*"csrf_token":"\([^"]*\)".*/\1/p')"
[ -n "$token" ] || { echo "нет csrf_token" >&2; exit 1; }
i=0
while [ "$i" -lt "$n" ]; do
  i=$((i + 1))
  code="$(curl -s -k "$@" -b "$jar" -o /dev/null -w '%{http_code}' \
    -H 'Content-Type: application/json' -H "Origin: $base" -H "X-CSRF-Token: $token" \
    -H "X-Forwarded-For: 198.51.100.$i" \
    --data '{"email":"nobody@example.test","password":"wrong-password-123456"}' "$base/api/auth/login")"
  codes="$codes $code"
done
rm -f "$jar"
echo "$codes"
