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
# Se puede repetir en otra cuenta (por ejemplo, la de la empresa): crea todo de cero con nombres nuevos.
set -euo pipefail
trap 'echo; echo "ERROR: el script se ha parado en la línea $LINENO. Copia el mensaje de arriba y pásaselo a Claude."' ERR

UBICACION="${UBICACION:-spaincentral}"        # región UE (Madrid)
SQL_PLAN="${SQL_PLAN:-basic}"                 # basic: ~5 $/mes, siempre encendida | gratis: oferta gratuita (no disponible en todas las regiones)
SUFIJO="${SUFIJO:-$(openssl rand -hex 3 | cut -c1-5)}"
RG="cuadralo-rg"
SQL_SERVER="cuadralo-sql-$SUFIJO"
SQL_DB="cuadralo"
SQL_ADMIN="cuadraloadmin"
STORAGE="cuadralost$SUFIJO"
CONTENEDOR="cargas"
KV="cuadralo-kv-$SUFIJO"
PLAN="cuadralo-plan"
APP="cuadralo-demo-$SUFIJO"

clave() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }
SQL_PASS="$(clave 20)Aa1#"
DJANGO_SECRET="$(clave 50)"
PASS_DIRECTOR="$(clave 14)"
PASS_CONTABLE="$(clave 14)"
PASS_PRUEBA="$(clave 14)"

echo "== 0/7 Activando los servicios de Azure en tu suscripción (la primera vez tarda 1-3 minutos)"
for proveedor in Microsoft.Sql Microsoft.Storage Microsoft.KeyVault Microsoft.Web Microsoft.CloudShell; do
  az provider register -n "$proveedor" --wait -o none
done

echo "== 1/7 Grupo de recursos $RG en $UBICACION"
az group create -n "$RG" -l "$UBICACION" -o none

echo "== 2/7 Azure SQL (plan: $SQL_PLAN)"
az sql server create -g "$RG" -n "$SQL_SERVER" -l "$UBICACION" -u "$SQL_ADMIN" -p "$SQL_PASS" --minimal-tls-version 1.2 -o none
az sql server firewall-rule create -g "$RG" -s "$SQL_SERVER" -n PermitirServiciosAzure \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none
if [ "$SQL_PLAN" = "gratis" ]; then
  az sql db create -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB" \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --capacity 2 \
    --use-free-limit --free-limit-exhaustion-behavior AutoPause --backup-storage-redundancy Local -o none
else
  az sql db create -g "$RG" -s "$SQL_SERVER" -n "$SQL_DB" \
    --edition Basic --capacity 5 --max-size 2GB --backup-storage-redundancy Local -o none
fi

echo "== 3/7 Almacenamiento privado para los Excels subidos"
az storage account create -g "$RG" -n "$STORAGE" -l "$UBICACION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none
STORAGE_KEY="$(az storage account keys list -g "$RG" -n "$STORAGE" --query '[0].value' -o tsv)"
az storage container create -n "$CONTENEDOR" --account-name "$STORAGE" --account-key "$STORAGE_KEY" -o none

echo "== 4/7 Key Vault para las claves"
az keyvault create -g "$RG" -n "$KV" -l "$UBICACION" --enable-rbac-authorization true -o none
KV_ID="$(az keyvault show -n "$KV" --query id -o tsv)"
YO="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create --assignee-object-id "$YO" --assignee-principal-type User \
  --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none
echo "   esperando a que el permiso se active (60 s)…"; sleep 60
guardar() { az keyvault secret set --vault-name "$KV" -n "$1" --value "$2" -o none; }
guardar django-secret-key "$DJANGO_SECRET"
guardar sql-password "$SQL_PASS"
guardar storage-key "$STORAGE_KEY"
guardar demo-password-director "$PASS_DIRECTOR"
guardar demo-password-contable "$PASS_CONTABLE"
guardar demo-password-prueba "$PASS_PRUEBA"

echo "== 5/7 Web (App Service, plan gratuito F1, Python 3.12)"
az appservice plan create -g "$RG" -n "$PLAN" -l "$UBICACION" --is-linux --sku F1 -o none
az webapp create -g "$RG" -p "$PLAN" -n "$APP" --runtime "PYTHON:3.12" -o none
az webapp update -g "$RG" -n "$APP" --https-only true -o none
APP_ID="$(az webapp identity assign -g "$RG" -n "$APP" --query principalId -o tsv)"
az role assignment create --assignee-object-id "$APP_ID" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none

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
