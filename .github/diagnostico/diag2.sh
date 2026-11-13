#!/bin/bash
# Se ejecuta en la consola Kudu de Azure. Entra como director.demo (contraseña de los ajustes de Azure, sin escribirla),
# abre algunas páginas y enseña el final del registro de errores. No cambia datos.
B="https://$WEBSITE_HOSTNAME"; J=/tmp/cj.txt; rm -f $J
curl -s -c $J -b $J "$B/entrar/" -o /tmp/l.html
T=$(grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' /tmp/l.html | cut -d'"' -f4)
curl -s -c $J -b $J -e "$B/entrar/" --data-urlencode "csrfmiddlewaretoken=$T" --data-urlencode "username=director.demo" \
     --data-urlencode "password=$DEMO_PASSWORD_DIRECTOR" "$B/entrar/" -o /dev/null -w "login %{http_code}\n"
for u in "/" "/?p=resumen" "/?p=ventas" "/?p=comparativa&hotel=MAR" "/cargas/"; do
  curl -s -b $J "$B$u" -o /dev/null -w "$u %{http_code}\n" --max-time 200
done
echo "--- registro de errores"
tail -n 60 /home/LogFiles/cuadralo-errores.log 2>/dev/null || echo "(sin archivo de errores)"
