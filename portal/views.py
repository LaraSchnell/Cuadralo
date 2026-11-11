import pandas as pd
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from urllib.parse import urlencode

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from cuadralo import apuntes as apuntes_mod
from cuadralo import calculos, informe
from cuadralo import exportar as exportar_xlsx
from .acceso import perfil_requerido
from .models import Carga, InteresModulo, Perfil
from .procesar import datos_empresa, leer_configuracion, presupuesto_empresa, procesar_empresa, registrar_carga

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']


def _mes_texto(ts):
    return f'{MESES[ts.month - 1]} {ts.year}'


class Seleccion:
    """Lo que el usuario está viendo: datos de su empresa, hoteles visibles, hotel elegido, mes y periodo.

    Los hoteles visibles salen SOLO del perfil (un director de hotel ve solo el suyo); lo que llega por
    la URL se valida contra esa lista y, si no encaja, se ignora.
    """

    def __init__(self, request):
        empresa, perfil = request.empresa, request.perfil
        self.datos = None
        mov, pms = datos_empresa(empresa)
        if len(mov) == 0 or len(pms) == 0:
            return
        cfg = leer_configuracion(empresa)
        datos = informe.Datos(mov, pms, presupuesto_empresa(empresa), cfg)
        if not datos.meses:
            return
        self.datos, self.cfg = datos, cfg
        self.visibles = list(cfg['hoteles']['Id hotel'])
        if perfil.rol == Perfil.DIRECTOR_HOTEL:
            self.visibles = [perfil.hotel]
        self.opciones_hotel = ([('GRUPO', 'Todo el grupo')] if len(self.visibles) > 1 else []) + \
            [(h, datos.nombres[h]) for h in self.visibles]
        self.seleccion = request.GET.get('hotel')
        if self.seleccion not in dict(self.opciones_hotel):
            self.seleccion = self.opciones_hotel[0][0]
        self.hoteles = self.visibles if self.seleccion == 'GRUPO' else [self.seleccion]
        try:
            mes = pd.Timestamp(request.GET['mes'] + '-01') if request.GET.get('mes') else None
        except ValueError:
            mes = None
        self.mes = mes if mes in datos.meses else datos.meses[0]
        self.modo = 'acumulado' if request.GET.get('periodo') == 'acumulado' else 'mes'

    def contexto(self):
        return {'mes': self.mes, 'mes_texto': _mes_texto(self.mes), 'modo': self.modo, 'seleccion': self.seleccion,
                'opciones_hotel': self.opciones_hotel,
                'meses': [(m.strftime('%Y-%m'), _mes_texto(m)) for m in self.datos.meses]}


@perfil_requerido
def inicio(request):
    empresa = request.empresa
    contexto = {'empresa': empresa, 'perfil': request.perfil, 'informe': None, 'meses': []}
    sel = Seleccion(request)
    if sel.datos is None:
        return render(request, 'portal/inicio.html', contexto)
    contenido = informe.construir(sel.datos, sel.visibles, sel.seleccion, sel.mes, sel.modo)
    ultima = Carga.objects.filter(empresa=empresa, estado='ok').order_by('-creada').first()
    contexto.update(sel.contexto())
    contexto.update({
        'informe': contenido, 'ultima_carga': ultima, 'pagina': request.GET.get('p', 'resumen'),
        'filtros_url': urlencode({'hotel': sel.seleccion, 'mes': sel.mes.strftime('%Y-%m'), 'periodo': sel.modo}),
        'intereses': set(InteresModulo.objects.filter(empresa=empresa, usuario=request.user).values_list('modulo', flat=True)),
    })
    return render(request, 'portal/inicio.html', contexto)


def _excel(contenido, nombre):
    r = HttpResponse(contenido, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    r['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return r


@perfil_requerido
def exportar(request, que):
    """Descarga una tabla del informe (o el informe entero) en Excel, con los mismos filtros que la pantalla."""
    if que != 'informe' and que not in exportar_xlsx.TABLAS:
        raise Http404
    sel = Seleccion(request)
    if sel.datos is None:
        raise Http404
    try:
        hojas = exportar_xlsx.hojas_informe(sel.datos, que, sel.hoteles, sel.visibles, sel.mes, sel.modo)
    except KeyError:
        raise Http404
    titulo = 'Grupo' if len(sel.hoteles) > 1 else sel.datos.nombres[sel.hoteles[0]]
    periodo = _mes_texto(sel.mes) if sel.modo == 'mes' else f'acumulado a {_mes_texto(sel.mes)}'
    contenido = exportar_xlsx.libro(hojas, f'{request.empresa.nombre} · {titulo}', periodo, request.empresa.datos_ficticios)
    nombre = f'Cuadralo_{que}_{slugify(titulo)}_{sel.mes:%Y-%m}{"_acumulado" if sel.modo == "acumulado" else ""}.xlsx'
    return _excel(contenido, nombre)


def _filtros_apuntes(request, sel):
    g = request.GET
    fecha = lambda k: pd.Timestamp(g[k]) if g.get(k) else None
    try:
        desde, hasta = fecha('desde'), fecha('hasta')
    except ValueError:
        desde = hasta = None
    if desde is None and hasta is None:  # por defecto, el mes elegido
        desde = sel.mes
        hasta = sel.mes + pd.offsets.MonthEnd(0)
    try:
        importe_min = float(g['importe_min'].replace(',', '.')) if g.get('importe_min') else None
    except ValueError:
        importe_min = None
    por = g.get('agrupar') if g.get('agrupar') in apuntes_mod.AGRUPACIONES else 'proveedor'
    return {'desde': desde, 'hasta': hasta, 'proveedor': g.get('proveedor') or None, 'ceco': g.get('ceco') or None,
            'linea': g.get('linea') or None, 'bloque': g.get('bloque') or None, 'cuenta': g.get('cuenta') or None,
            'texto': g.get('texto') or None, 'importe_min': importe_min}, por


@perfil_requerido
def apuntes(request):
    """Explorador de apuntes contables con filtros y agrupación; exporta a Excel lo que se ve en pantalla."""
    empresa = request.empresa
    contexto = {'empresa': empresa, 'perfil': request.perfil, 'sin_datos': True}
    sel = Seleccion(request)
    if sel.datos is None:
        return render(request, 'portal/apuntes.html', contexto)
    lineas = apuntes_mod.preparar(calculos.asignar_lineas(sel.datos.mov, sel.cfg))
    lineas = lineas[lineas['Id hotel'].isin(sel.visibles)]          # nunca apuntes de hoteles que no puede ver
    filtros, por = _filtros_apuntes(request, sel)
    actual = apuntes_mod.filtrar(lineas, sel.hoteles, **filtros)
    filtros_aa = {**filtros, 'desde': filtros['desde'] - pd.DateOffset(years=1) if filtros['desde'] is not None else None,
                  'hasta': filtros['hasta'] - pd.DateOffset(years=1) if filtros['hasta'] is not None else None}
    anterior = apuntes_mod.filtrar(lineas, sel.hoteles, **filtros_aa)
    resumen = apuntes_mod.agrupar(actual, anterior, por, sel.datos.nombres)
    detalle = apuntes_mod.tabla_detalle(actual, sel.datos.nombres)

    if request.GET.get('exportar'):
        titulo = 'Grupo' if len(sel.hoteles) > 1 else sel.datos.nombres[sel.hoteles[0]]
        rango = f'{filtros["desde"]:%d/%m/%Y} - {filtros["hasta"]:%d/%m/%Y}' if filtros['desde'] is not None and filtros['hasta'] is not None else 'todas las fechas'
        aplicados = ', '.join(f'{k}: {v}' for k, v in filtros.items() if v is not None and k not in ('desde', 'hasta')) or 'ninguno'
        col = apuntes_mod.AGRUPACIONES[por][1]
        hojas = [
            ('Resumen', f'Apuntes agrupados por {col.lower()} · {rango} · filtros: {aplicados}', resumen,
             {'Importe': 'eur', 'Año anterior': 'eur', 'Diferencia': 'eur', 'Var %': 'var', 'Apuntes': 'int', 'Mes': 'fecha'}),
            ('Apuntes', f'Apuntes contables · {rango} · filtros: {aplicados}', detalle,
             {'Importe sin IVA': 'eur', 'Fecha de registro': 'fecha', 'Fecha de emisión': 'fecha'}),
        ]
        contenido = exportar_xlsx.libro(hojas, f'{empresa.nombre} · {titulo}', rango, empresa.datos_ficticios)
        return _excel(contenido, f'Cuadralo_apuntes_{slugify(titulo)}_{filtros["desde"]:%Y-%m-%d}.xlsx'
                      if filtros['desde'] is not None else f'Cuadralo_apuntes_{slugify(titulo)}.xlsx')

    visibles_sel = lineas[lineas['Id hotel'].isin(sel.hoteles)]
    est = sel.cfg['estructura_informe']
    max_filas = 500
    contexto.update(sel.contexto())
    contexto.update({
        'sin_datos': False, 'f': filtros, 'por': por, 'agrupaciones': [(k, v[1]) for k, v in apuntes_mod.AGRUPACIONES.items()],
        'proveedores': sorted(visibles_sel['Proveedor'].dropna().unique()),
        'cecos': sorted(visibles_sel['Ceco'].dropna().unique()),
        'lineas': [l for l in est[est['Tipo'] == 'Detalle']['Línea'] if l != 'Reserva FF&E'],
        'bloques': list(dict.fromkeys(est[est['Tipo'] == 'Detalle']['Bloque'])),
        'resumen': resumen.to_dict('records'), 'col_resumen': apuntes_mod.AGRUPACIONES[por][1],
        'detalle': detalle.head(max_filas).to_dict('records'), 'total_apuntes': len(detalle), 'max_filas': max_filas,
        'total_importe': float(actual['Importe sin IVA'].sum()), 'total_aa': float(anterior['Importe sin IVA'].sum()),
        'url_exportar': request.GET.urlencode() + ('&' if request.GET else '') + 'exportar=1',
    })
    return render(request, 'portal/apuntes.html', contexto)


@require_POST
@perfil_requerido
def interes(request):
    """«Me interesa este módulo»: se guarda por empresa y usuario para medir la demanda antes de construirlo."""
    modulo = request.POST.get('modulo')
    if modulo not in dict(InteresModulo.MODULOS):
        return JsonResponse({'ok': False}, status=400)
    InteresModulo.objects.get_or_create(empresa=request.empresa, usuario=request.user, modulo=modulo)
    return JsonResponse({'ok': True})


@perfil_requerido
def subir(request):
    if not request.perfil.puede_subir:
        raise PermissionDenied('Tu usuario no puede subir archivos.')
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        archivos = request.FILES.getlist('archivos')
        if tipo not in dict(Carga.TIPOS) or not archivos:
            messages.error(request, 'Elige el tipo de archivo y al menos un Excel.')
            return redirect('subir')
        malos = [a.name for a in archivos if not a.name.lower().endswith('.xlsx')]
        if malos:
            messages.error(request, f'Solo se aceptan archivos .xlsx: {", ".join(malos)}')
            return redirect('subir')
        for a in archivos:
            registrar_carga(request.empresa, request.user, tipo, a)
        ok, mensaje = procesar_empresa(request.empresa)
        (messages.success if ok else messages.error)(request, mensaje)
        return redirect('inicio' if ok else 'cargas')
    return render(request, 'portal/subir.html', {'empresa': request.empresa, 'perfil': request.perfil, 'tipos': Carga.TIPOS})


@perfil_requerido
def cargas(request):
    lista = Carga.objects.filter(empresa=request.empresa).select_related('usuario')[:200]
    return render(request, 'portal/cargas.html', {'empresa': request.empresa, 'perfil': request.perfil, 'cargas': lista})
