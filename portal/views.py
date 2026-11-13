import copy
import re
import threading

import pandas as pd
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from urllib.parse import urlencode

from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import Count, Max, Sum
from django.db.models.functions import Abs
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from cuadralo import apuntes as apuntes_mod
from cuadralo import calculos, informe
from cuadralo import exportar as exportar_xlsx
from .acceso import perfil_requerido
from . import precalculo, procesar, segundo_plano
from .models import (Carga, InteresModulo, MapeoAprobado, MovimientoContable, Perfil, Propuesta, Reserva,
                     ResultadoEmpresa)
from .procesar import (carga_identica, datos_empresa, huella_de, leer_configuracion, presupuesto_empresa,
                       registrar_carga, reservas_empresa)

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']


def _mes_texto(ts):
    return f'{MESES[ts.month - 1]} {ts.year}'


# Datos ya calculados de cada empresa, en memoria del proceso. Se rehacen solo cuando cambian sus cargas
# o su configuración, así cada clic no vuelve a leer y calcular todo el histórico.
_CACHE_DATOS = {}
# La web corre con varios hilos: solo uno carga los datos de una empresa; los demás esperan y los reutilizan.
_CANDADO_DATOS = threading.Lock()


def _version(empresa):
    v = Carga.objects.filter(empresa=empresa, estado='ok').aggregate(n=Count('id'), ultima=Max('id'))
    # El último precálculo guardado también cuenta: cada procesado crea filas nuevas en ResultadoEmpresa
    pre = ResultadoEmpresa.objects.filter(empresa=empresa).aggregate(m=Max('id'))['m']
    return (v['n'], v['ultima'], empresa.configuracion.name, pre)


def obtener_datos(empresa):
    """Datos de la empresa para el informe: precalculados al procesar (se leen, no se recalculan).

    Si aún no hay precálculo (empresa procesada con una versión anterior), se rehace una vez.
    """
    version = _version(empresa)
    guardado = _CACHE_DATOS.get(empresa.id)
    if guardado and guardado[0] == version:
        return guardado[1], guardado[2]
    with _CANDADO_DATOS:
        guardado = _CACHE_DATOS.get(empresa.id)
        if guardado and guardado[0] == version:
            return guardado[1], guardado[2]
        return _cargar_datos(empresa, version)


def _cargar_datos(empresa, version):
    cfg = leer_configuracion(empresa)
    datos = precalculo.cargar(empresa, cfg)
    if datos is None:
        # Sin precálculo (versión anterior o cargas eliminadas): se rehace en segundo plano, nunca con la web esperando
        tipos = set(empresa.cargas.filter(estado='ok').values_list('tipo', flat=True))
        if {Carga.BUSINESS_CENTRAL, Carga.OPERADOR} <= tipos and not segundo_plano.en_marcha(empresa.id):
            segundo_plano.lanzar(empresa.id)
            datos = precalculo.cargar(empresa, cfg)
    if datos is None or not datos.meses:
        return None, None
    _CACHE_DATOS[empresa.id] = (version, datos, cfg)
    return datos, cfg


PAGINAS = [('resumen', 'Resumen'), ('ventas', 'Ventas y ocupación'), ('resultados', 'Cuenta de resultados'),
           ('desviaciones', 'Desviaciones'), ('cuadre', 'Cuadre'), ('comparativa', 'Comparativa')]
PAGINAS_DIRECTOR_HOTEL = {'resumen', 'ventas', 'resultados', 'desviaciones'}


def paginas_de(perfil):
    """Qué páginas del informe ve cada perfil. Dirección y contabilidad ven todo; el director de hotel, lo de su hotel."""
    if perfil.rol == Perfil.DIRECTOR_HOTEL:
        return [p for p in PAGINAS if p[0] in PAGINAS_DIRECTOR_HOTEL]
    return PAGINAS


def _resumir(valores):
    if not valores:
        return ''
    return valores[0] if len(valores) == 1 else f'{valores[0]} y {len(valores) - 1} más'


class Seleccion:
    """Lo que el usuario está viendo: datos de su empresa, hoteles, meses y filtros de ceco, proveedor y canal.

    Los hoteles visibles salen SOLO del perfil (un director de hotel ve solo el suyo); lo que llega por
    la URL se valida contra esa lista y, si no encaja, se ignora. Igual con meses, cecos, proveedores y canales.
    """

    def __init__(self, request):
        empresa, perfil = request.empresa, request.perfil
        g = request.GET
        self.datos = None
        datos, cfg = obtener_datos(empresa)
        if datos is None:
            return
        self.datos, self.cfg = datos, cfg
        self.visibles = list(cfg['hoteles']['Id hotel'])
        if perfil.rol == Perfil.DIRECTOR_HOTEL:
            self.visibles = [perfil.hotel]
        # hoteles: varios a la vez; 'GRUPO' o nada = todos los visibles
        pedidos = [h for h in g.getlist('hotel') if h in self.visibles]
        self.hoteles = pedidos or list(self.visibles)
        self.todos = len(self.hoteles) == len(self.visibles)
        self.seleccion = 'GRUPO' if len(self.hoteles) > 1 else self.hoteles[0]
        self.opciones_hotel = ([('GRUPO', 'Todo el grupo')] if len(self.visibles) > 1 else []) + \
            [(h, datos.nombres[h]) for h in self.visibles]
        # meses: varios a la vez (meses=AAAA-MM repetido). Compatibilidad: mes=AAAA-MM y periodo=acumulado
        disponibles = set(datos.meses)
        leer = lambda t: pd.Timestamp(t + '-01') if re.fullmatch(r'20\d\d-\d\d', t or '') else None
        meses = sorted({m for m in (leer(t) for t in g.getlist('meses')) if m in disponibles})
        if not meses:
            mes = leer(g.get('mes', ''))
            mes = mes if mes in disponibles else datos.meses[0]
            meses = [m for m in informe._periodo(mes, 'acumulado') if m in disponibles] \
                if g.get('periodo') == 'acumulado' else [mes]
        self.meses = meses
        self.mes = meses[-1]
        self.modo = 'acumulado' if g.get('periodo') == 'acumulado' else 'mes'
        # filtros de gastos y de reservas
        a = datos.apuntes_agg[datos.apuntes_agg['Id hotel'].isin(self.visibles)]
        self.opciones_ceco = sorted(set(a['Ceco']))
        self.opciones_proveedor = sorted(set(a['Proveedor'].dropna()) - {''})
        self.opciones_canal = datos.canales
        self.ceco = [x for x in g.getlist('ceco') if x in self.opciones_ceco]
        self.proveedor = [x for x in g.getlist('proveedor') if x in self.opciones_proveedor]
        self.canal = [x for x in g.getlist('canal') if x in self.opciones_canal]

    @property
    def filtros(self):
        return {'ceco': self.ceco, 'proveedor': self.proveedor, 'canal': self.canal}

    def query(self, **cambios):
        """La selección actual como parámetros de URL (para enlaces, exportar y las tablas de detalle)."""
        partes = [('meses', f'{m:%Y-%m}') for m in self.meses]
        if not self.todos:
            partes += [('hotel', h) for h in self.hoteles]
        partes += [('ceco', x) for x in self.ceco] + [('proveedor', x) for x in self.proveedor] + [('canal', x) for x in self.canal]
        partes += list(cambios.items())
        return urlencode(partes)

    def contexto(self):
        anios = {}
        for m in sorted(self.datos.meses):
            anios.setdefault(m.year, []).append({'id': f'{m:%Y-%m}', 'texto': informe.MESES[m.month - 1].capitalize(),
                                                 'corto': informe.MESES_CORTOS[m.month - 1], 'sel': m in self.meses})
        arbol = [{'anio': a, 'meses': ms, 'todos': all(x['sel'] for x in ms), 'alguno': any(x['sel'] for x in ms)}
                 for a, ms in sorted(anios.items(), reverse=True)]
        etiquetas = []
        if not self.todos:
            etiquetas += [{'tipo': 'hotel', 'texto': self.datos.nombres[h], 'quitar': self._sin('hotel', h)} for h in self.hoteles]
        etiquetas += [{'tipo': 'ceco', 'texto': f'Ceco {x}', 'quitar': self._sin('ceco', x)} for x in self.ceco]
        etiquetas += [{'tipo': 'proveedor', 'texto': x, 'quitar': self._sin('proveedor', x)} for x in self.proveedor]
        etiquetas += [{'tipo': 'canal', 'texto': f'Canal {x}', 'quitar': self._sin('canal', x)} for x in self.canal]
        return {'mes': self.mes, 'mes_texto': informe.mes_texto(self.mes), 'modo': self.modo, 'seleccion': self.seleccion,
                'opciones_hotel': self.opciones_hotel, 'arbol_meses': arbol,
                'meses_sel': [f'{m:%Y-%m}' for m in self.meses], 'periodo_texto': informe.texto_periodo(self.meses),
                'f_hoteles': [{'valor': h, 'texto': self.datos.nombres[h], 'sel': h in self.hoteles and not self.todos}
                              for h in self.visibles],
                'f_cecos': [{'valor': x, 'texto': x, 'sel': x in self.ceco} for x in self.opciones_ceco],
                'f_proveedores': [{'valor': x, 'texto': x, 'sel': x in self.proveedor} for x in self.opciones_proveedor],
                'f_canales': [{'valor': x, 'texto': x, 'sel': x in self.canal} for x in self.opciones_canal],
                'etiquetas_filtro': etiquetas, 'query': self.query(),
                'txt_hotel': 'Todos' if self.todos else _resumir([self.datos.nombres[h] for h in self.hoteles]),
                'txt_ceco': _resumir(self.ceco) or 'Todos', 'txt_proveedor': _resumir(self.proveedor) or 'Todos',
                'txt_canal': _resumir(self.canal) or 'Todos',
                'meses': [(f'{m:%Y-%m}', informe.mes_texto(m)) for m in self.datos.meses]}

    def _sin(self, campo, valor):
        copia = copy.copy(self)
        if campo == 'hotel':
            copia.hoteles = [h for h in self.hoteles if h != valor] or list(self.visibles)
            copia.todos = len(copia.hoteles) == len(self.visibles)
        else:
            setattr(copia, campo, [x for x in getattr(self, campo) if x != valor])
        return copia.query()


@perfil_requerido
def inicio(request):
    empresa = request.empresa
    contexto = {'empresa': empresa, 'perfil': request.perfil, 'informe': None, 'meses': [], 'paginas': paginas_de(request.perfil)}
    sel = Seleccion(request)
    if sel.datos is None:
        return render(request, 'portal/inicio.html', contexto)
    contenido = informe.construir(sel.datos, sel.visibles, sel.hoteles, sel.meses, filtros=sel.filtros)
    ultima = Carga.objects.filter(empresa=empresa, estado='ok').order_by('-creada').first()
    contexto.update(sel.contexto())
    visibles_p = {p for p, _ in contexto['paginas']}
    pagina = request.GET.get('p', 'resumen')
    contexto.update({
        'informe': contenido, 'ultima_carga': ultima, 'pagina': pagina if pagina in visibles_p or pagina in MODULOS else 'resumen',
        'filtros_url': sel.query(), 'paginas_visibles': visibles_p,
        'intereses': set(InteresModulo.objects.filter(empresa=empresa, usuario=request.user).values_list('modulo', flat=True)),
    })
    return render(request, 'portal/inicio.html', contexto)


MODULOS = {'reputacion', 'personas', 'operaciones'}
MAX_FILAS_DETALLE = 300


@perfil_requerido
def detalle(request):
    """Tabla de detalle de un clic en un gráfico o en una fila: de qué facturas o de qué reservas sale la cifra.

    Respeta siempre la selección y los hoteles que el usuario puede ver; el resultado son filas ya calculadas.
    """
    sel = Seleccion(request)
    if sel.datos is None:
        raise Http404
    g = request.GET
    datos = sel.datos
    hoteles = sel.hoteles
    if g.get('hotel_sel') in sel.visibles:
        hoteles = [g['hotel_sel']]
    meses = sel.meses
    if g.get('mes_sel'):
        m = pd.Timestamp(g['mes_sel'] + '-01') if re.fullmatch(r'20\d\d-\d\d', g['mes_sel']) else None
        if m not in datos.meses:
            raise Http404
        meses = [m]
    nombre = lambda h: datos.nombres.get(h, h)
    p_txt = informe.texto_periodo(meses)
    donde = ', '.join(nombre(h) for h in hoteles) if len(hoteles) < len(sel.visibles) or len(sel.visibles) == 1 else 'todo el grupo'
    tipo = g.get('tipo')
    if tipo == 'facturas':
        q = MovimientoContable.objects.filter(empresa=request.empresa, hotel__in=hoteles,
                                              mes__in=[m.date() for m in meses])   # siempre su empresa y sus hoteles
        if sel.ceco:
            q = q.filter(ceco__in=['' if c == '(sin ceco)' else c for c in sel.ceco])
        if sel.proveedor:
            q = q.filter(proveedor__in=sel.proveedor)
        que = 'todas las líneas'
        if g.get('linea'):
            q, que = q.filter(linea=g['linea']), g['linea']
        elif g.get('bloque'):
            q, que = q.filter(bloque=g['bloque']), g['bloque']
        tot = q.aggregate(n=Count('id'), total=Sum('importe'))
        total, n = float(tot['total'] or 0), tot['n']
        filas = [[f'{x.fecha_registro:%d/%m/%Y}', nombre(x.hotel), x.num_documento, x.num_documento_externo, x.proveedor,
                  x.descripcion, x.linea, x.ceco or '(sin ceco)', informe.eur(x.importe, 2)]
                 for x in q.order_by(Abs('importe').desc(), 'id')[:MAX_FILAS_DETALLE]]
        explicacion = [f'{informe.num(n)} apuntes de Business Central suman {informe.eur(total, 2)}.',
                       'Es la cifra de esta línea en la cuenta de resultados' + (' (con el filtro de ceco o proveedor aplicado).'
                                                                                if sel.ceco or sel.proveedor else '.')]
        return JsonResponse({'titulo': f'Facturas de {que} · {donde} · {p_txt}', 'explicacion': explicacion,
                             'columnas': ['Fecha', 'Hotel', 'Nº documento', 'Nº factura proveedor', 'Proveedor', 'Descripción',
                                          'Línea', 'Ceco', 'Importe sin IVA'],
                             'numericas': [8], 'filas': filas, 'total_filas': n, 'max_filas': MAX_FILAS_DETALLE,
                             'orden': 'las de mayor importe; el resto, en Excel',
                             'exportar': reverse('apuntes') + '?' + sel.query(**({'linea': g['linea']} if g.get('linea') else {}))})
    if tipo == 'reservas':
        if not datos.hay_reservas:
            return JsonResponse({'titulo': 'Sin reservas', 'explicacion': ['Todavía no se han cargado reservas del PMS.'],
                                 'columnas': [], 'filas': [], 'total_filas': 0})
        canal = [g['canal_sel']] if g.get('canal_sel') in sel.opciones_canal else sel.canal
        # totales: de las reservas ya agregadas (cuadran con el informe)
        m = datos.reservas_mes(hoteles, meses, canal)
        if g.get('segmento'):
            m = m[m['Segmento'] == g['segmento']]
        if g.get('nacionalidad'):
            m = m[m['Nacionalidad'] == g['nacionalidad']]
        noches, ingresos = float(m['Noches'].sum()), float(m['Ingresos'].sum())
        # filas: consulta a la base de datos, solo estancias que tocan el periodo, paginada
        inicio, fin = min(meses), max(meses) + pd.offsets.MonthBegin(1)
        q = Reserva.objects.filter(empresa=request.empresa, hotel__in=hoteles, estancia=True, noches__gt=0,
                                   llegada__lt=fin.date(), salida__gt=inicio.date())
        if canal:
            q = q.filter(canal__in=canal)
        if g.get('segmento'):
            q = q.filter(segmento=g['segmento'])
        if g.get('nacionalidad'):
            q = q.filter(nacionalidad=g['nacionalidad'])
        dias_sel = {d.date() for mes in meses for d in pd.date_range(mes, mes + pd.offsets.MonthEnd(0))}
        filas, total_filas = [], q.count()
        for x in q.order_by('llegada', 'hotel', 'numero')[:MAX_FILAS_DETALLE]:
            noches_p = sum(1 for d in pd.date_range(x.llegada, x.salida - pd.Timedelta(days=1)) if d.date() in dias_sel)
            ing_p = float(x.ingresos) * noches_p / x.noches if x.noches else 0
            ant = (x.llegada - x.fecha_creacion.date()).days if x.fecha_creacion else None
            filas.append([x.numero, nombre(x.hotel), x.canal, x.segmento, x.tarifa, f'{x.llegada:%d/%m/%Y}', f'{x.salida:%d/%m/%Y}',
                          noches_p, x.adultos + x.ninos, x.nacionalidad, informe.eur(ing_p, 2),
                          f'{ant} días' if ant is not None else ''])
        habitaciones = int(datos.cfg['hoteles'].set_index('Id hotel').loc[hoteles, 'Habitaciones'].sum())
        dias = sum(x.days_in_month for x in meses)
        disponibles = habitaciones * dias
        explicacion = [f'{informe.num(total_filas)} reservas suman {informe.num(noches)} noches '
                       f'y {informe.eur(ingresos, 2)} de alojamiento en el periodo.',
                       f'Ocupación = {informe.num(noches)} noches / ({habitaciones} habitaciones × {dias} días) = '
                       f'{informe.pct(noches / disponibles if disponibles else None)}.'
                       if not (canal or g.get('segmento') or g.get('nacionalidad')) else
                       f'Supone el {informe.pct(noches / disponibles if disponibles else None)} de las habitaciones disponibles '
                       f'({habitaciones} × {dias} días).',
                       f'ADR = {informe.eur(ingresos, 2)} / {informe.num(noches)} noches = {informe.eur(ingresos / noches if noches else None, 2)}.']
        filtro = ' · '.join(x for x in [', '.join(canal) if canal else '', g.get('segmento', ''), g.get('nacionalidad', '')] if x)
        return JsonResponse({'titulo': f'Reservas · {donde} · {p_txt}' + (f' · {filtro}' if filtro else ''),
                             'explicacion': explicacion,
                             'columnas': ['Nº reserva', 'Hotel', 'Canal', 'Segmento', 'Tarifa', 'Llegada', 'Salida',
                                          'Noches del periodo', 'Personas', 'País', 'Ingresos del periodo', 'Antelación'],
                             'numericas': [7, 8, 10], 'filas': filas, 'total_filas': total_filas, 'max_filas': MAX_FILAS_DETALLE,
                             'orden': 'por fecha de llegada'})
    raise Http404


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
        hojas = exportar_xlsx.hojas_informe(sel.datos, que, sel.hoteles, sel.visibles, sel.meses, 'lista')
    except KeyError:
        raise Http404
    titulo = 'Grupo' if len(sel.hoteles) > 1 else sel.datos.nombres[sel.hoteles[0]]
    periodo = informe.texto_periodo(sel.meses)
    contenido = exportar_xlsx.libro(hojas, f'{request.empresa.nombre} · {titulo}', periodo, request.empresa.datos_ficticios)
    nombre = f'Cuadralo_{que}_{slugify(titulo)}_{sel.meses[0]:%Y-%m}' + (f'_a_{sel.mes:%Y-%m}' if len(sel.meses) > 1 else '') + '.xlsx'
    return _excel(contenido, nombre)


def _filtros_apuntes(request, sel):
    g = request.GET
    fecha = lambda k: pd.Timestamp(g[k]) if g.get(k) else None
    try:
        desde, hasta = fecha('desde'), fecha('hasta')
    except ValueError:
        desde = hasta = None
    if desde is None and hasta is None:  # por defecto, el mes elegido
        desde = sel.meses[0]
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
    filtros, por = _filtros_apuntes(request, sel)
    # Se leen de la base de datos solo los apuntes de sus hoteles y de las fechas pedidas (y las mismas un año antes)
    desde_aa = filtros['desde'] - pd.DateOffset(years=1) if filtros['desde'] is not None else None
    lineas = apuntes_mod.preparar(precalculo.apuntes_rango(empresa, sel.hoteles, desde_aa, filtros['hasta']))
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

    est = sel.cfg['estructura_informe']
    max_filas = 500
    contexto.update(sel.contexto())
    contexto.update({
        'sin_datos': False, 'f': filtros, 'por': por, 'agrupaciones': [(k, v[1]) for k, v in apuntes_mod.AGRUPACIONES.items()],
        'proveedores': sel.opciones_proveedor,
        'cecos': sel.opciones_ceco,
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
        nuevos = 0
        for a in archivos:
            huella = huella_de(a)
            igual = carga_identica(request.empresa, huella)
            if igual:
                quien = igual.usuario.username if igual.usuario else 'otro usuario'
                messages.warning(request, (
                    f'«{a.name}» no se ha subido: es idéntico a «{igual.nombre_original}», que subió {quien} el '
                    f'{timezone.localtime(igual.creada):%d/%m/%Y a las %H:%M}. Si quieres cambiarlo, elimina antes '
                    f'el anterior en el historial de cargas.'))
                continue
            registrar_carga(request.empresa, request.user, tipo, a, huella)
            nuevos += 1
        if nuevos:
            segundo_plano.lanzar(request.empresa.id)
            messages.success(request, f'{nuevos} archivo(s) recibido(s). Se están procesando: el informe se '
                                      'actualizará solo en unos minutos. Puedes seguir trabajando.')
        return redirect('cargas')
    return render(request, 'portal/subir.html', {'empresa': request.empresa, 'perfil': request.perfil, 'tipos': Carga.TIPOS})


@perfil_requerido
def cargas(request):
    lista = (Carga.objects.filter(empresa=request.empresa).exclude(estado='eliminada')
             .select_related('usuario')[:200])
    return render(request, 'portal/cargas.html', {
        'empresa': request.empresa, 'perfil': request.perfil, 'cargas': lista,
        'procesando': request.empresa.procesando, 'por_confirmar': request.empresa.por_confirmar})


@perfil_requerido
def revisar(request):
    """Lo que los archivos traen y la configuración no conoce: Cuádralo propone y el usuario confirma."""
    if not request.perfil.puede_subir:
        raise PermissionDenied('Tu usuario no puede confirmar la configuración.')
    pendientes = list(Propuesta.objects.filter(empresa=request.empresa, estado='pendiente').select_related('carga'))
    if request.method == 'POST':
        elegidas, faltan = {}, []
        for p in pendientes:
            valor = request.POST.get(f'p_{p.id}', '')
            if valor not in {v for v, _ in p.opciones}:
                faltan.append(p)
            else:
                elegidas[p.id] = valor
        if faltan:
            messages.error(request, f'Falta elegir una opción en {len(faltan)} pregunta(s).')
        else:
            cargas = set()
            for p in pendientes:
                valor = elegidas[p.id]
                origen, destino = (valor, p.clave) if p.modo == 'falta' else (p.clave, valor)
                MapeoAprobado.objects.update_or_create(
                    empresa=request.empresa, tipo=p.tipo, clase=p.clase, origen=origen,
                    defaults={'destino': destino, 'sugerencia': p.sugerencia, 'fuente': p.fuente,
                              'confianza': p.confianza, 'aprobado_por': request.user})
                p.estado = 'aprobada'
                p.save(update_fields=['estado'])
                cargas.add(p.carga_id)
            Carga.objects.filter(id__in=cargas, estado='revisar').update(estado='pendiente', mensaje='')
            segundo_plano.lanzar(request.empresa.id)
            messages.success(request, f'{len(pendientes)} respuesta(s) guardada(s). Los archivos se están procesando '
                                      'y la próxima vez no se volverá a preguntar.')
            return redirect('cargas')
    grupos = {}
    for p in pendientes:
        grupos.setdefault(p.carga, []).append(p)
    return render(request, 'portal/revisar.html', {
        'empresa': request.empresa, 'perfil': request.perfil, 'grupos': grupos.items(),
        'elegidas': request.POST if request.method == 'POST' else {}})


@require_POST
@perfil_requerido
def eliminar_carga(request, carga_id):
    if not request.perfil.puede_subir:
        raise PermissionDenied('Tu usuario no puede eliminar archivos.')
    # Aislamiento: la carga se busca SOLO dentro de la empresa del usuario
    carga = get_object_or_404(Carga, id=carga_id, empresa=request.empresa)
    if carga.estado == 'eliminada':
        return redirect('cargas')
    if carga.estado == 'pendiente':
        messages.error(request, 'Espera a que termine de procesarse para eliminarlo.')
        return redirect('cargas')
    procesar.eliminar_carga(carga, request.user)
    segundo_plano.lanzar(request.empresa.id)
    messages.success(request, f'«{carga.nombre_original}» eliminado. El informe se está recalculando sin ese archivo.')
    return redirect('cargas')
