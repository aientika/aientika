#!/usr/bin/env bash
# Despliegue del conector MCP.
#
# Este script no ejecuta nada contra la nube. Declara qué se desplegaría (rama, HEAD, árbol limpio y diferencias en ambos
# sentidos con origin/main) e imprime los comandos de despliegue, para que quien despliega los corra a mano, con su cuenta,
# después de revisarlos.
# Aborta si el árbol no está limpio: la imagen sale de un clon del commit, nunca del árbol de trabajo.
#
# Uso:  BD_HOST=<IP privada de la base de datos> bash scripts/deploy_conector.sh
# La conexión a la base va con TLS que verifica la CA de la instancia: REPLICA_DB_CA sale del secreto `db-ca`.
set -euo pipefail

cd "$(dirname "$0")/.."

PROYECTO="${PROYECTO:?define PROYECTO (tu proyecto de Google Cloud)}"
CUENTA="${CUENTA:?define CUENTA (la cuenta de gcloud con permiso de despliegue)}"
REGION="us-east1"
SERVICIO="aientika-conector"  # nombre del producto, va en la URL que pega el colega
REPO_IMAGENES="conector"
SA="conector-mcp"
SECRETO_BD="db-password-conector"  # contraseña del rol `conector` (mínimo privilegio), NUNCA la de postgres
SECRETO_VOYAGE="voyage-api-key"
SECRETO_FIRMA="conector-firma-secret"
PROYECTO_VOYAGE="${PROYECTO_VOYAGE:-$PROYECTO}"  # proyecto donde está la clave de Voyage; Cloud Run solo lee secretos de su propio proyecto
OPT_OUT_VOYAGE="2026-11-07"  # constancia del opt-out
RED="default"
SUBRED="default"
BD_HOST="${BD_HOST:-}"
# Ids de invitado con cupo de administrador (limites.FACTOR_ADMINISTRADOR). --set-env-vars REEMPLAZA todas las
# variables: si esta no va, un despliegue completo le quita el cupo al administrador sin avisar.
ADMINISTRADORES="${ADMINISTRADORES:-}"
# Presupuesto mensual de la capa gratuita dinámica (valor de ejemplo, ajustalo). Vacío = topes fijos. Como ADMINISTRADORES: si no va, --set-env-vars la borra.
PRESUPUESTO="${PRESUPUESTO:-100}"
BD_USUARIO="${BD_USUARIO:-conector}"   # el servicio NO se conecta como postgres: ver scripts/conector_rol.sql
HILOS=16                              # = src.conector.servidor.HILOS: la concurrencia de Cloud Run no pasa de los hilos

RAMA="$(git rev-parse --abbrev-ref HEAD)"
SHA="$(git rev-parse HEAD)"
SUCIO="$(git status --short)"

echo "== Qué se desplegaría =="
echo "Rama:  ${RAMA}"
echo "HEAD:  ${SHA}"
echo "git status --short:"
if [ -n "${SUCIO}" ]; then
  echo "${SUCIO}"
  echo "[ABORTADO] El árbol no está limpio. Commit y push primero: se despliega un commit, no un árbol de trabajo."
  exit 1
fi
echo "(vacío)"
if [ -z "${BD_HOST}" ]; then
  echo "[ABORTADO] Falta BD_HOST (IP privada de la instancia Cloud SQL base-de-datos): sin ella el servicio no llega a la base."
  exit 1
fi
git fetch --quiet origin main || echo "[AVISO] No se pudo actualizar origin/main; las diferencias pueden estar viejas."
echo "Commits en HEAD que no están en origin/main (lo que GANA si se despliega sin mergear):"
git log --oneline origin/main..HEAD || true
echo "Commits en origin/main que no están en HEAD (lo que PIERDE):"
git log --oneline HEAD..origin/main || true
echo "Entorno destino: servicio nuevo (no hay versión en marcha que se pise). Migración de datos: ninguna en el despliegue;"
echo "las tablas del conector las crea 'python scripts/conector_invitados.py esquema' (paso 6)."
echo

IMAGEN="${REGION}-docker.pkg.dev/${PROYECTO}/${REPO_IMAGENES}/conector:${SHA}"
ID="--project=${PROYECTO} --account=${CUENTA}"

echo "== Comandos para revisar y correr a mano (cuenta ${CUENTA}) =="
echo
echo "# 1. APIs"
echo "gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com ${ID}"
echo
echo "# 2. Cuenta de servicio con mínimo privilegio y sin claves JSON: solo lee SUS tres secretos; no tiene roles de Cloud SQL"
echo "gcloud iam service-accounts create ${SA} --display-name='Conector MCP' ${ID}"
echo
echo "# 3. Secretos (los crea el equipo; nada de esto se imprime ni se guarda en el repo)"
echo "#    ${SECRETO_BD}: NO existe todavía. Se crea con la contraseña del rol 'conector' (la misma que recibe conector_rol.sql en el paso 6):"
echo "CLAVE=\$(python -c \"import secrets; print(secrets.token_urlsafe(32), end='')\")"
echo "printf %s \"\$CLAVE\" | gcloud secrets create ${SECRETO_BD} --data-file=- --replication-policy=automatic ${ID}"
echo "#    ${SECRETO_VOYAGE}: copiarlo desde ${PROYECTO_VOYAGE} sin mostrarlo (el valor viaja por la tubería, no por pantalla):"
echo "gcloud secrets versions access latest --secret=${SECRETO_VOYAGE} --project=${PROYECTO_VOYAGE} --account=${CUENTA} | gcloud secrets create ${SECRETO_VOYAGE} --data-file=- --replication-policy=automatic ${ID}"
echo "#    ${SECRETO_FIRMA}: clave nueva de firma de tokens (>= 32 caracteres), generada y guardada sin mostrarse:"
echo "python -c \"import secrets; print(secrets.token_urlsafe(48), end='')\" | gcloud secrets create ${SECRETO_FIRMA} --data-file=- --replication-policy=automatic ${ID}"
for S in "${SECRETO_BD}" "${SECRETO_VOYAGE}" "${SECRETO_FIRMA}"; do
  echo "gcloud secrets add-iam-policy-binding ${S} --member=serviceAccount:${SA}@${PROYECTO}.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor ${ID}"
done
echo
echo "# 4. Imagen desde un clon limpio del commit ${SHA}"
echo "gcloud artifacts repositories create ${REPO_IMAGENES} --repository-format=docker --location=${REGION} ${ID}   # si no existe"
# core.longpaths: en Windows, sin esto el checkout del clon FALLA por rutas largas y deja un árbol a
# medias que igual se puede empaquetar. `git status --short` vacío en el clon es la prueba de que está entero.
echo "CLON=\$(mktemp -d) && git clone -c core.autocrlf=false -c core.longpaths=true --quiet $(pwd) \"\$CLON\" && git -C \"\$CLON\" checkout --quiet ${SHA}"
echo "test -z \"\$(git -C \"\$CLON\" status --short)\" || { echo '[ABORTADO] el clon no quedó entero'; exit 1; }"
echo "cp \"\$CLON/Dockerfile.conector\" \"\$CLON/Dockerfile\"   # solo en el clon: el build usa el archivo con el nombre Dockerfile"
echo "gcloud builds submit \"\$CLON\" --tag=${IMAGEN} ${ID}"
echo
echo "# 5. Servicio. URL pública = la canónica de Cloud Run (se calcula, no se escribe): el issuer de OAuth sale de ella."
echo "NUMERO=\$(gcloud projects describe ${PROYECTO} --format='value(projectNumber)' --account=${CUENTA})"
echo "URL=\"https://${SERVICIO}-\${NUMERO}.${REGION}.run.app\""
echo "gcloud run deploy ${SERVICIO} --image=${IMAGEN} --region=${REGION} --service-account=${SA}@${PROYECTO}.iam.gserviceaccount.com \\"
echo "  --min-instances=0 --max-instances=3 --concurrency=${HILOS} --cpu=1 --memory=1Gi --timeout=60 --allow-unauthenticated \\"
echo "  --network=${RED} --subnet=${SUBRED} --vpc-egress=private-ranges-only \\"
echo "  --set-secrets=REPLICA_DB_PASSWORD=${SECRETO_BD}:latest,VOYAGE_API_KEY=${SECRETO_VOYAGE}:latest,CONECTOR_FIRMA_SECRET=${SECRETO_FIRMA}:latest,REPLICA_DB_CA=db-ca:latest \\"
# Delimitador ^@^ y no la coma: CONECTOR_HOSTS_EXTRA es una lista separada por comas y se partiría en silencio.
# Ver `gcloud topic escaping`.
echo "  --set-env-vars=^@^REPLICA_DB_HOST=${BD_HOST}@REPLICA_DB_NAME=replica@REPLICA_DB_USER=${BD_USUARIO}@VOYAGE_OPT_OUT_CONFIRMADO=${OPT_OUT_VOYAGE}@CONECTOR_COMMIT=${SHA}@CONECTOR_URL_PUBLICA=\${URL}@CONECTOR_ADMINISTRADORES=${ADMINISTRADORES}@CONECTOR_PRESUPUESTO_USD=${PRESUPUESTO} \\"
echo "  ${ID}"
echo "#    La invitación lleva EXACTAMENTE \${URL}/mcp. La otra URL del servicio (la del hash, ...-ue.a.run.app) NO está entre los"
echo "#    hosts aceptados y da 421. Si hiciera falta, se agrega su host en CONECTOR_HOSTS_EXTRA con el mismo ^@^."
echo "#    --allow-unauthenticated es a propósito: el servicio es su propio servidor OAuth y Claude debe poder alcanzarlo;"
echo "#    la autenticación está en la app (código de invitado). CONECTOR_SIN_AUTH NO se define aquí nunca."
echo "#    Direct VPC egress: sin conector VPC de pago. Firewall: solo tcp:5432 desde el rango de la subred."
echo
echo "# 6. Tablas, rol e invitados (con la base encendida; ANTES de abrir el servicio)"
echo "python scripts/conector_invitados.py esquema                       # con el rol dueño de la base (REPLICA_DB_USER/PASSWORD del equipo)"
echo "psql -h ${BD_HOST} -U <rol dueño> -d replica -v clave=\"\$CLAVE\" -f scripts/conector_rol.sql   # crea el rol ${BD_USUARIO}: sin superusuario"
echo "python scripts/conector_invitados.py alta --etiqueta 'Nombre del colega'   # muestra el código UNA vez"
echo
echo "# 7. Verificación de RESULTADOS, no de componentes"
echo "curl -s \${URL}/version                      # debe traer commit ${SHA}"
echo "curl -s \${URL}/.well-known/oauth-authorization-server | grep -c refresh_token   # debe dar 0"
echo "# luego conectar en claude.ai web, Desktop y móvil con \${URL}/mcp."
echo
echo "# 7b. Actualización (servicio ya creado): --update-env-vars no borra las demás variables"
echo "gcloud run deploy ${SERVICIO} --image=${IMAGEN} --region=${REGION} --update-env-vars=CONECTOR_COMMIT=${SHA} ${ID}"
echo "#    y /version debe traer ${SHA}"
