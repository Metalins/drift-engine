#!/usr/bin/env bash
# set-db-url-secret.sh — crea/actualiza el secret METALINS_DB_URL en GCP.
#
# Defaults harcoded para nuestro Supabase (Transaction Pooler sa-east-1).
# Solo pide password (oculto). URL-encodea automáticamente.
# El password nunca aparece en pantalla, logs ni history.
#
# Si en el futuro cambian los datos del Supabase (rotación de proyecto, etc.),
# editá las constantes arriba.

set -euo pipefail

# --- defaults Metalins/Supabase ---
SECRET_NAME="metalins-db-url"
PG_HOST="aws-1-sa-east-1.pooler.supabase.com"
PG_PORT="6543"
PG_USER="postgres.ttxautbynuelvpbvengc"
PG_DB="postgres"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { printf "${GREEN}▶${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail() { printf "${RED}✗ %s${NC}\n" "$*" >&2; exit 1; }

command -v gcloud >/dev/null || fail "gcloud CLI no encontrado."

log "Destino: $PG_USER@$PG_HOST:$PG_PORT/$PG_DB (Supabase Transaction Pooler sa-east-1)"
log "Secret name: $SECRET_NAME"
echo

# Password sin echo
printf "Supabase DB password (no se muestra): "
read -s DBPW
echo
[ -n "$DBPW" ] || fail "Password no puede ser vacío."

# --- URL-encode el password y construir connection string ---
log "URL-encodeando password..."
DB_URL="$(DBPW="$DBPW" PGHOST="$PG_HOST" PGPORT="$PG_PORT" PGUSER="$PG_USER" PGDB="$PG_DB" python3 - <<'PY'
import urllib.parse, os
pw = os.environ["DBPW"]
encoded = urllib.parse.quote(pw, safe="")
print(f"postgresql://{os.environ['PGUSER']}:{encoded}@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDB']}")
PY
)"
[ -n "$DB_URL" ] || fail "No se pudo construir el connection string."

# --- subir a Secret Manager ---
if gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  log "Secret $SECRET_NAME ya existe → agregando nueva versión."
  printf "%s" "$DB_URL" | gcloud secrets versions add "$SECRET_NAME" --data-file=- >/dev/null
else
  log "Creando secret $SECRET_NAME..."
  printf "%s" "$DB_URL" | gcloud secrets create "$SECRET_NAME" --data-file=- >/dev/null
fi

# Borrar la variable de memoria por las dudas
unset DBPW DB_URL

log "✅ Secret $SECRET_NAME listo en Secret Manager."
echo
echo "Próximo paso: re-deployar para que el server lea el nuevo secret."
echo "  bash deploy-cloudrun.sh"
echo
