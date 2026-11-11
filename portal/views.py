import pandas as pd
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from cuadralo import calculos, reglas
from .acceso import perfil_requerido
from .models import Carga, Perfil
from .procesar import datos_empresa, leer_configuracion, presupuesto_empresa, procesar_empresa, registrar_carga

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']


def _mes_texto(ts):
    return f'{MESES[ts.month - 1]} {ts.year}'


@perfil_requerido
def inicio(request):
    empresa, perfil = request.empresa, request.perfil
    mov, pms = datos_empresa(empresa)
    contexto = {'empresa': empresa, 'perfil': perfil, 'filas': [], 'meses': []}
    if len(mov) == 0 or len(pms) == 0:
        return render(request, 'portal/inicio.html', contexto)

    cfg = leer_configuracion(empresa)
    pyg = calculos.cuenta_resultados(mov, cfg)
    act = calculos.actividad(pms, cfg)
    meses = sorted(set(act.index.get_level_values('Mes')) & set(pyg.index.get_level_values('Mes')), reverse=True)
    pedido = request.GET.get('mes')
    mes = pd.Timestamp(pedido + '-01') if pedido and pd.Timestamp(pedido + '-01') in meses else meses[0]

    nombres = cfg['hoteles'].set_index('Id hotel')['Hotel']
    hoteles = list(nombres.index)
    if perfil.rol == Perfil.DIRECTOR_HOTEL:
        hoteles = [perfil.hotel]

    filas = []
    for h in hoteles:
        if (h, mes) not in pyg.index or (h, mes) not in act.index:
            continue
        p, a = pyg.loc[(h, mes)], act.loc[(h, mes)]
        filas.append({'hotel': nombres[h], 'ingresos': p['Total ingresos'], 'gop': p['GOP'],
                      'gop_pct': p['% GOP'], 'ocupacion': a['Ocupación'], 'adr': a['ADR'],
                      'rn': a['Room nights'], 'disp': a['Habitaciones disponibles'], 'aloj': a['Alojamiento']})
    total = None
    if len(filas) > 1:
        ing = sum(f['ingresos'] for f in filas)
        gop = sum(f['gop'] for f in filas)
        rn = sum(f['rn'] for f in filas)
        total = {'hotel': 'Total grupo', 'ingresos': ing, 'gop': gop, 'gop_pct': gop / ing if ing else None,
                 'ocupacion': rn / sum(f['disp'] for f in filas), 'adr': sum(f['aloj'] for f in filas) / rn}
    contexto.update({'filas': filas, 'total': total, 'mes': mes, 'mes_texto': _mes_texto(mes),
                     'meses': [(m.strftime('%Y-%m'), _mes_texto(m)) for m in meses]})
    return render(request, 'portal/inicio.html', contexto)


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


def _registros(df, hoteles_visibles, nombres):
    if df is None or not len(df):
        return []
    df = df[df['Id hotel'].isin(hoteles_visibles)].copy()
    df['Hotel'] = df['Id hotel'].map(nombres)
    return df.to_dict('records')


@perfil_requerido
def analisis(request):
    """Cuadre con contabilidad, ratios del operador, alertas de facturas y desviaciones explicadas."""
    empresa, perfil = request.empresa, request.perfil
    mov, pms = datos_empresa(empresa)
    contexto = {'empresa': empresa, 'perfil': perfil}
    if len(mov) == 0 or len(pms) == 0:
        return render(request, 'portal/analisis.html', contexto)
    cfg = leer_configuracion(empresa)
    pres = presupuesto_empresa(empresa)
    m = calculos.asignar_lineas(mov, cfg)
    pyg = calculos.cuenta_resultados(mov, cfg)
    meses = sorted(set(pd.to_datetime(pms['Fecha'])) & set(pyg.index.get_level_values('Mes')), reverse=True)
    pedido = request.GET.get('mes')
    mes = pd.Timestamp(pedido + '-01') if pedido and pd.Timestamp(pedido + '-01') in meses else meses[0]
    r = reglas.analizar_mes(m, pms, pres, pyg, cfg, mes)
    nombres = cfg['hoteles'].set_index('Id hotel')['Hotel'].to_dict()
    visibles = [perfil.hotel] if perfil.rol == Perfil.DIRECTOR_HOTEL else list(nombres)
    cuadre = r['cuadre']
    cuadre_vis = cuadre[cuadre['Id hotel'].isin(visibles)]
    orden_causa = {'Sin causa': 0, 'Factura': 1, 'Cuadre': 2, 'Calendario': 3, 'Ingresos': 4, 'Actividad': 5}
    desv = r['desviaciones']
    if len(desv):
        desv = desv.assign(_o=desv['Tipo de causa'].map(orden_causa)).sort_values(['_o', 'Id hotel', 'Línea'])
    contexto.update({
        'mes_texto': _mes_texto(mes), 'meses': [(x.strftime('%Y-%m'), _mes_texto(x)) for x in meses],
        'cuadre_mal': _registros(cuadre_vis[~cuadre_vis['Cuadra']], visibles, nombres),
        'cuadre_ok': int(cuadre_vis['Cuadra'].sum()), 'cuadre_total': len(cuadre_vis),
        'ratios_mal': _registros(r['ratios'][~r['ratios']['Correcto']], visibles, nombres),
        'alertas': _registros(r['alertas'], visibles, nombres),
        'desviaciones': _registros(desv, visibles, nombres),
        'version': r['version_reglas'],
    })
    return render(request, 'portal/analisis.html', contexto)
