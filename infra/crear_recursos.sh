#!/bin/bash
# Cuádralo · crea todos los recursos de Azure del MVP en región UE.
#
# Cómo usarlo (sin instalar nada):
#   Región y plan de base de datos: UBICACION=spaincentral SQL_PLAN=basic bash crear_recursos.sh (valores por defecto)
#   1. Entra en portal.azure.com y abre Cloud Shell (icono >_ arriba). Elige "Bash".
#   2. Sube este archivo con el botón "Cargar o descargar archivos" o pégalo en un archivo nuevo.
#   3. Ejecuta:  bash crear_recursos.sh
#   4. Al final verás lo que tienes que copiar en GitHub. También queda guardado en ~/cuadralo_resumen.txt
#
# Si se para, vuelve a ejecutarlo: reutiliza lo ya creado (nombres y claves en ~/cuadralo_estado.env).
# En otra cuenta (por ejemplo, la de la empresa) crea todo de cero con nombres nuevos.
set -euo pipefail
trap 'echo; echo "ERROR: el script se ha parado en la línea $LINENO. Copia el mensaje de arriba y pásaselo a Claude."' ERR

UBICACION="${UBICACION:-spaincentral}"        # región UE (Madrid)
SQL_PLAN="${SQL_PLAN:-basic}"                 # basic: ~5 $/mes, siempre encendida | gratis: oferta gratuita (no disponible en todas las regiones)
RG="cuadralo-rg"
ESTADO="$HOME/cuadralo_estado.env"            # guarda nombres y claves para poder repetir el script sin empezar de cero
clave() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }
if [ -f "$ESTADO" ]; then
  source "$ESTADO"
else
  EXISTENTE="$(az sql server list -g "$RG" --query '[0].name' -o tsv 2>/dev/null || true)"
  SUFIJO="${SUFIJO:-${EXISTENTE#cuadralo-sql-}}"
  SUFIJO="${SUFIJO:-$(openssl rand -hex 3 | cut -c1-5)}"
  SQL_PASS="$(clave 20)Aa1#"
  DJANGO_SECRET="$(clave 50)"
  PASS_DIRECTOR="$(clave 14)"
  PASS_CONTABLE="$(clave 14)"
  PASS_PRUEBA="$(clave 14)"
  umask 077
  printf 'SUFIJO=%q\nSQL_PASS=%q\nDJANGO_SECRET=%q\nPASS_DIRECTOR=%q\nPASS_CONTABLE=%q\nPASS_PRUEBA=%q\n' \
    "$SUFIJO" "$SQL_PASS" "$DJANGO_SECRET" "$PASS_DIRECTOR" "$PASS_CONTABLE" "$PASS_PRUEBA" > "$ESTADO"
fi
echo "Nombres con el sufijo: $SUFIJO (si el script se para, vuelve a ejecutarlo y continuará)"

# Azure a veces tarda en "ver" un recurso recién creado: repite la comprobación hasta 5 minutos.
esperar() {
  for i in $(seq 1 30); do
    "$@" -o none 2>/dev/null && return 0
    echo "   esperando a que Azure termine de crear el recurso ($i/30)…"; sleep 10
  done
  "$@" -o none
}
existe() { "$@" -o none 2>/dev/null; }
SQL_SERVER="cuadralo-sql-$SUFIJO"
SQL_DB="cuadralo"
SQL_ADMIN="cuadraloadmin"
STORAGE="cuadralost$SUFIJO"
CONTENEDOR="cargas"
KV="cuadralo-kv-$SUFIJO"
PLAN="cuadralo-plan"
APP="cuadralo-demo-$SUFIJO"


echo "== 0/7 Activando los servicios de Azure en tu suscripción (la primera vez tarda 1-3 minutos)"
for proveedor in Microsoft.Sql Microsoft.Storage Microsoft.KeyVault Microsoft.Web Microsoft.CloudShell; do
  az provider register -n "$proveedor" --wait -o none
done

echo "== 1/7 Grupo de recursos $RG en $UBICACION"
az group create -n "$RG" -l "$UBICACION" -o none

echo "== 2/7 Azure SQL (plan: $SQL_PLAN)"
existe az sql server show -g "$RG" -n "$SQL_SERVER" || \
  az sql server create -g "$RG" -n "$SQL_SERVER" -l "$UBICACION" -u "$SQL_ADMIN" -p "$SQL_PASS" --minimal-tls-version 1.2 -o none
esperar az sql server show -g "$RG" -n "$SQL_SERVER"
az sql server update -g "$RG" -n "$SQL_SERVER" -p "$SQL_PASS" -o none   # la contraseña siempre coincide con la guardada
az sql server firewall-rule create -g "$RG" -s "$SQL_SERVER" -n PermitirServiciosAzure \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none
if existe az sql db show -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB"; then
  echo "   la base de datos ya existe"
elif [ "$SQL_PLAN" = "gratis" ]; then
  az sql db create -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB" \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --capacity 2 \
    --use-free-limit --free-limit-exhaustion-behavior AutoPause --backup-storage-redundancy Local -o none
else
  az sql db create -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB" \
    --edition Basic --capacity 5 --max-size 2GB --backup-storage-redundancy Local -o none
fi

echo "== 3/7 Almacenamiento privado para los Excels subidos"
existe az storage account show -g "$RG" -n "$STORAGE" || \
  az storage account create -g "$RG" -n "$STORAGE" -l "$UBICACION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none
esperar az storage account show -g "$RG" -n "$STORAGE"
STORAGE_KEY="$(az storage account keys list -g "$RG" -n "$STORAGE" --query '[0].value' -o tsv)"
az storage container create -n "$CONTENEDOR" --account-name "$STORAGE" --account-key "$STORAGE_KEY" -o none 2>/dev/null

echo "== 4/7 Key Vault para las claves"
existe az keyvault show -g "$RG" -n "$KV" || \
  az keyvault create -g "$RG" -n "$KV" -l "$UBICACION" --enable-rbac-authorization true -o none
esperar az keyvault show -g "$RG" -n "$KV"
KV_ID="$(az keyvault show -n "$KV" --query id -o tsv)"
YO="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create --assignee-object-id "$YO" --assignee-principal-type User \
  --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none 2>/dev/null || true
echo "   esperando a que el permiso se active (60 s)…"; sleep 60
guardar() { esperar az keyvault secret set --vault-name "$KV" -n "$1" --value "$2"; }
guardar django-secret-key "$DJANGO_SECRET"
guardar sql-password "$SQL_PASS"
guardar storage-key "$STORAGE_KEY"
guardar demo-password-director "$PASS_DIRECTOR"
guardar demo-password-contable "$PASS_CONTABLE"
guardar demo-password-prueba "$PASS_PRUEBA"

echo "== 5/7 Web (App Service, plan gratuito F1, Python 3.12)"
existe az appservice plan show -g "$RG" -n "$PLAN" || \
  az appservice plan create -g "$RG" -n "$PLAN" -l "$UBICACION" --is-linux --sku F1 -o none
esperar az appservice plan show -g "$RG" -n "$PLAN"
existe az webapp show -g "$RG" -n "$APP" || \
  az webapp create -g "$RG" -p "$PLAN" -n "$APP" --runtime "PYTHON:3.12" -o none
esperar az webapp show -g "$RG" -n "$APP"
az webapp update -g "$RG" -n "$APP" --https-only true -o none
APP_ID="$(az webapp identity assign -g "$RG" -n "$APP" --query principalId -o tsv)"
az role assignment create --assignee-object-id "$APP_ID" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none 2>/dev/null || true

echo "== 6/7 Configuración de la web (las claves se leen de Key Vault, no se copian)"
ref() { echo "@Microsoft.KeyVault(VaultName=$KV;SecretName=$1)"; }
az webapp config appsettings set -g "$RG" -n "$APP" -o none --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  DJANGO_SECRET_KEY="$(ref django-secret-key)" \
  AZURE_SQL_SERVER="$SQL_SERVER.database.windows.net" AZURE_SQL_DATABASE="$SQL_DB" AZURE_SQL_USER="$SQL_ADMIN" \
  AZURE_SQL_PASSWORD="$(ref sql-password)" \
  AZURE_STORAGE_ACCOUNT_NAME="$STORAGE" AZURE_STORAGE_ACCOUNT_KEY="$(ref storage-key)" AZURE_STORAGE_CONTAINER="$CONTENEDOR" \
  DEMO_PASSWORD_DIRECTOR="$(ref demo-password-director)" DEMO_PASSWORD_CONTABLE="$(ref demo-password-contable)" \
  DEMO_PASSWORD_PRUEBA="$(ref demo-password-prueba)"
az webapp config set -g "$RG" -n "$APP" --startup-file "bash startup.sh" -o none

echo "== 7/7 Permiso para que GitHub publique la web"
az resource update -g "$RG" --name scm --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies \
  --parent "sites/$APP" --set properties.allow=true -o none
az webapp deployment list-publishing-profiles -g "$RG" -n "$APP" --xml > ~/cuadralo_perfil_publicacion.xml

cat > ~/cuadralo_resumen.txt <<EOF
==================== CUÁDRALO · RESUMEN ====================
Web:            https://$APP.azurewebsites.net
Grupo de recursos: $RG ($UBICACION)

Copia en GitHub (repositorio cuadralo → Settings → Secrets and variables → Actions):
  1. Pestaña "Variables" → New repository variable
       Nombre: AZURE_WEBAPP_NAME     Valor: $APP
  2. Pestaña "Secrets" → New repository secret
       Nombre: AZURE_WEBAPP_PUBLISH_PROFILE
       Valor: todo el contenido del archivo ~/cuadralo_perfil_publicacion.xml
              (en Cloud Shell: cat ~/cuadralo_perfil_publicacion.xml , selecciona todo y copia)

Usuarios del Grupo Demo (guárdalos en tu gestor de contraseñas; también están en Key Vault $KV):
  director.demo   $PASS_DIRECTOR
  contable.demo   $PASS_CONTABLE
  usuario.prueba  $PASS_PRUEBA   (empresa "Hotel Prueba Aislamiento")
=============================================================
EOF
cat ~/cuadralo_resumen.txt
