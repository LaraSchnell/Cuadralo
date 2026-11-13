"""Cuádralo · prepara el contenido del informe para la web.

Recibe el modelo común de una empresa y una selección (meses, hoteles, ceco, proveedor, canal) y devuelve
un diccionario listo para las plantillas: tarjetas, gráficos (con sus etiquetas, sus textos de ayuda y lo
que filtra cada clic), tablas, cuadre, desviaciones con su causa y alertas.

Todas las cifras salen de calculos.py, reglas.py y reservas.py. Los textos son plantillas fijas rellenadas
con esas cifras; ningún texto ni número lo genera la IA. El navegador solo dibuja lo que llega de aquí.
"""
import pandas as pd

from . import calculos as c
from . import reglas as r
from . import reservas as rv

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']
MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
MAX_ALERTAS_PORTADA = 5
MAX_PARTIDAS_GRAFICO = 10


# ---------------------------------------------------------------- formato español

def num(v, dec=0):
    if v is None or v != v:
        return '—'
    texto = f'{abs(float(v)):,.{dec}f}'.replace(',', '§').replace('.', ',').replace('§', '.')
    return ('−' if float(v) < 0 and round(abs(float(v)), dec) != 0 else '') + texto


def eur(v, dec=0):
    return '—' if v is None or v != v else f'{num(v, dec)} €'


def pct(v, dec=1):
    return '—' if v is None or v != v else f'{num(float(v) * 100, dec)} %'


def con_signo(v, dec=1, unidad='%'):
    if v is None or v != v:
        return None
    s = num(v, dec)
    return ('+' if round(float(v), dec) > 0 else ('±' if round(float(v), dec) == 0 else '')) + s + ' ' + unidad


def corto(v):
    """Importe corto para escribir encima de una barra: 1,2 M€ · 373 k€ · 950 €."""
    if v is None or v != v:
        return ''
    a = abs(float(v))
    if a >= 1_000_000:
        return f'{num(v / 1_000_000, 1)} M€'
    if a >= 10_000:
        return f'{num(v / 1000)} k€'
    if a >= 1000:
        return f'{num(v / 1000, 1)} k€'
    return eur(v)


def mes_texto(ts):
    return f'{MESES[ts.month - 1]} {ts.year}'


def mes_corto(ts):
    return f'{MESES_CORTOS[ts.month - 1]} {str(ts.year)[2:]}'


def texto_periodo(meses):
    """'octubre 2026' · 'enero-octubre 2026' · 'sep 26, oct 26 y dic 26' (3 meses)."""
    meses = sorted(meses)
    if len(meses) == 1:
        return mes_texto(meses[0])
    seguidos = all((b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in zip(meses, meses[1:]))
    if seguidos:
        if meses[0].year == meses[-1].year:
            return f'{MESES[meses[0].month - 1]}-{MESES[meses[-1].month - 1]} {meses[-1].year} ({len(meses)} meses)'
        return f'{mes_corto(meses[0])} - {mes_corto(meses[-1])} ({len(meses)} meses)'
    if len(meses) <= 4:
        return ', '.join(mes_corto(m) for m in meses[:-1]) + f' y {mes_corto(meses[-1])}'
    return f'{len(meses)} meses entre {mes_corto(meses[0])} y {mes_corto(meses[-1])}'


# ---------------------------------------------------------------- tarjetas KPI

# nombre, clave en kpis(), formato, tipo de variación, sentido (+1 subir es bueno, −1 subir es malo), fórmula
TARJETAS = {
    'portada': [
        ('Ingresos totales', 'Ingresos totales', 'eur', 'rel', 1, 'Suma de las líneas de ingreso en contabilidad'),
        ('GOP', 'GOP', 'eur', 'rel', 1, 'Ingresos − consumos − personal − otros gastos operativos'),
        ('% GOP', '% GOP', 'pct', 'pp', 1, 'GOP / ingresos totales'),
        ('Ocupación', 'Ocupación', 'pct', 'pp', 1, 'Room nights / (habitaciones × días)'),
        ('ADR', 'ADR', 'eur2', 'rel', 1, 'Ingresos de alojamiento del operador / room nights'),
        ('RevPAR', 'RevPAR', 'eur2', 'rel', 1, 'Ingresos de alojamiento / (habitaciones × días)'),
        ('GOPPAR', 'GOPPAR', 'eur2', 'rel', 1, 'GOP / (habitaciones × días)'),
        ('Labor cost', 'Labor cost', 'pct', 'pp', -1, 'Total personal / ingresos totales. Subir es malo'),
    ],
    'ventas': [
        ('Room nights', 'Room nights', 'num', 'rel', 1, 'Noches vendidas según el operador'),
        ('TRevPAR', 'TRevPAR', 'eur2', 'rel', 1, 'Ingresos totales / (habitaciones × días)'),
        ('Captación de desayunos', 'Captación desayunos', 'pct', 'pp', 1, 'Desayunos / (room nights × pax por habitación)'),
        ('Precio medio desayuno', 'Precio medio desayuno', 'eur2', 'rel', 1, 'Ingresos de desayunos / desayunos servidos'),
    ],
    'resultados': [
        ('AGOP', 'AGOP', 'eur', 'rel', 1, 'GOP − honorarios del operador − reserva FF&E'),
        ('GOP2', 'GOP2', 'eur', 'rel', 1, 'AGOP − tributos − amortizaciones − gastos financieros'),
        ('CPOR', 'CPOR', 'eur2', 'rel', -1, '(Personal hotel + otros gastos operativos) / room nights. Subir es malo'),
        ('Margen de desayunos', 'Margen desayunos', 'eur', 'rel', 1, 'Ingresos − consumo − personal de desayunos'),
    ],
    # tarjetas de las páginas nuevas
    'resumen': [
        ('Ingresos', 'Ingresos totales', 'eur', 'rel', 1, 'Suma de las líneas de ingreso en contabilidad'),
        ('GOP', 'GOP', 'eur', 'rel', 1, 'Ingresos − consumos − personal − otros gastos operativos'),
        ('% GOP', '% GOP', 'pct', 'pp', 1, 'GOP / ingresos'),
        ('Ocupación', 'Ocupación', 'pct', 'pp', 1, 'Room nights / (habitaciones × días)'),
        ('ADR', 'ADR', 'eur2', 'rel', 1, 'Ingresos de alojamiento / room nights'),
        ('RevPAR', 'RevPAR', 'eur2', 'rel', 1, 'Ingresos de alojamiento / (habitaciones × días)'),
    ],
    'ocupacion': [
        ('Room nights', 'Room nights', 'num', 'rel', 1, 'Noches vendidas según el operador'),
        ('Ocupación', 'Ocupación', 'pct', 'pp', 1, 'Room nights / (habitaciones × días)'),
        ('ADR', 'ADR', 'eur2', 'rel', 1, 'Ingresos de alojamiento / room nights'),
        ('RevPAR', 'RevPAR', 'eur2', 'rel', 1, 'Ingresos de alojamiento / (habitaciones × días)'),
    ],
    'cuenta': [
        ('Ingresos', 'Ingresos totales', 'eur', 'rel', 1, 'Suma de las líneas de ingreso'),
        ('Gastos operativos', 'Gastos operativos', 'eur', 'rel', -1, 'Consumos + personal + otros gastos operativos. Subir es malo'),
        ('GOP', 'GOP', 'eur', 'rel', 1, 'Ingresos − gastos operativos'),
        ('% GOP', '% GOP', 'pct', 'pp', 1, 'GOP / ingresos'),
        ('AGOP', 'AGOP', 'eur', 'rel', 1, 'GOP − honorarios del operador − reserva FF&E'),
        ('GOP2', 'GOP2', 'eur', 'rel', 1, 'AGOP − tributos − amortizaciones − gastos financieros'),
    ],
}


def _formato(v, f):
    return {'eur': eur(v), 'eur2': eur(v, 2), 'pct': pct(v), 'num': num(v), 'num1': num(v, 1)}[f]


def _variacion(actual, ref, tipo, sentido):
    if actual is None or ref is None:
        return None
    if tipo == 'pp':
        d = (actual - ref) * 100
        texto = con_signo(d, 1, 'pp')
    else:
        if not ref:
            return None
        d = (actual - ref) / abs(ref) * 100
        texto = con_signo(d, 1, '%')
    if round(d, 1) == 0:
        estado = 'neutro'
    else:
        estado = 'bien' if d * sentido > 0 else 'mal'
    return {'texto': texto, 'estado': estado, 'flecha': '▲' if d > 0.05 else ('▼' if d < -0.05 else '■')}


def tarjetas(grupo, k_real, k_ppto, k_aa):
    out = []
    for nombre, clave, f, tipo, sentido, formula in TARJETAS[grupo]:
        out.append({'nombre': nombre, 'valor': _formato(k_real.get(clave), f), 'formula': formula,
                    'ppto': _variacion(k_real.get(clave), k_ppto.get(clave) if k_ppto else None, tipo, sentido),
                    'aa': _variacion(k_real.get(clave), k_aa.get(clave) if k_aa else None, tipo, sentido)})
    return out


def franja_presupuesto(k_real, k_ppto, k_aa):
    """Bloques de color «Hasta el presupuesto» (diseño 3b). Todo sale de los KPIs ya calculados; nada lo escribe una IA.

    Las palancas de room nights y ADR se calculan sobre los INGRESOS que faltan (no sobre el GOP), para no suponer
    qué parte de cada euro vendido llega al GOP.
    """
    g = lambda d, k: (d or {}).get(k)
    bloques = []
    gop, gop_p, gop_a = g(k_real, 'GOP'), g(k_ppto, 'GOP'), g(k_aa, 'GOP')
    if gop is not None and gop_p is not None:
        d = gop - gop_p
        bloques.append({'que': 'GOP que falta para el presupuesto' if d < 0 else 'GOP por encima del presupuesto',
                        'cifra': eur(abs(d)), 'estado': 'mal' if d < 0 else 'bien',
                        'como': f'real {eur(gop)} frente a {eur(gop_p)}'})
    if gop is not None and gop_a is not None:
        d = gop - gop_a
        bloques.append({'que': 'GOP frente al año anterior', 'cifra': ('+' if d >= 0 else '−') + eur(abs(d)),
                        'estado': 'bien' if d >= 0 else 'mal', 'como': f'el año anterior fue {eur(gop_a)}'})
    ing, ing_p, rn, adr = g(k_real, 'Ingresos totales'), g(k_ppto, 'Ingresos totales'), g(k_real, 'Room nights'), g(k_real, 'ADR')
    if ing is not None and ing_p is not None:
        falta = ing_p - ing
        if falta > 0 and adr:
            bloques.append({'que': 'Room nights que faltan al ADR actual', 'cifra': num(falta / adr),
                            'estado': 'mal', 'como': f'para los {eur(falta)} de ingresos que faltan, a {eur(adr, 2)}'})
            if rn:
                bloques.append({'que': 'Subida de ADR que lo cubriría', 'cifra': eur(falta / rn, 2),
                                'estado': 'aviso', 'como': f'con las mismas {num(rn)} room nights'})
        else:
            bloques.append({'que': 'Ingresos por encima del presupuesto', 'cifra': eur(-falta), 'estado': 'bien',
                            'como': f'real {eur(ing)} frente a {eur(ing_p)}'})
    ocu, ocu_p = g(k_real, 'Ocupación'), g(k_ppto, 'Ocupación')
    if len(bloques) < 4 and ocu is not None and ocu_p is not None:
        d = (ocu - ocu_p) * 100
        bloques.append({'que': 'Ocupación frente al presupuesto', 'cifra': con_signo(d, 1, 'pts'),
                        'estado': 'bien' if d >= 0 else 'mal', 'como': f'{pct(ocu)} frente a {pct(ocu_p)}'})
    return bloques[:4]


# ---------------------------------------------------------------- agregación

def _suma(df, hoteles, meses):
    """Suma las filas de los hoteles y meses pedidos. Devuelve None si no hay ninguna."""
    if df is None or len(df) == 0:
        return None
    idx = [(h, m) for h in hoteles for m in meses if (h, m) in df.index]
    if not idx:
        return None
    return df.loc[idx].sum()


def _periodo(mes, modo='mes'):
    """Meses de un periodo: una lista ya hecha, el mes solo o el acumulado del año hasta ese mes."""
    if isinstance(mes, (list, tuple)):
        return sorted(mes)
    if modo == 'acumulado':
        return [pd.Timestamp(mes.year, m, 1) for m in range(1, mes.month + 1)]
    return [mes]


def _filas(df, hoteles, meses):
    """Filas (hotel, mes) de un detalle con índice (Id hotel, Mes)."""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    h = df.index.get_level_values('Id hotel')
    m = df.index.get_level_values('Mes')
    return df[h.isin(hoteles) & m.isin(meses)]


def calcular_desviaciones(hist, det_real, det_ppto, act, cuadre, cfg, hotel, mes):
    """Desviaciones de un hotel y un mes con sus causas y las 8 facturas más grandes de cada línea.

    hist: apuntes del hotel con su línea del informe (al menos los 13 meses hasta `mes`).
    """
    desv = r.desviaciones(None, det_real, det_ppto, act, cuadre, cfg, [hotel], mes, hist=hist)
    apuntes = hist[(hist['Mes'] == mes) & (hist['Id hotel'] == hotel)]
    for d in desv:
        ap = apuntes[apuntes['Línea'] == d['Línea']]
        ap = ap.reindex(ap['Importe sin IVA'].abs().sort_values(ascending=False).index).head(8)
        d['Apuntes'] = [{'fecha': f'{a:%d/%m/%Y}', 'doc': doc, 'proveedor': prov, 'descripcion': desc, 'importe': eur(imp, 2)}
                        for a, doc, prov, desc, imp in zip(ap['Fecha de registro'], ap['Nº documento'], ap['Proveedor'],
                                                           ap['Descripción'], ap['Importe sin IVA'])]
    return desv


CLAVES_PRECALCULO = ['det_real', 'det_ppto', 'act', 'cuadre', 'ratios', 'res_agg', 'res_llegadas', 'apuntes_agg']


class Datos:
    """Todo lo calculado de una empresa: se reutiliza en todas las páginas y selecciones.

    Dos formas de crearlo:
    - Datos(mov, pms, pres, cfg, res): calcula todo a partir del modelo común (al procesar las cargas y en las pruebas).
    - Datos.desde_precalculo(tablas, cfg, fuente_desviaciones): solo carga tablas ya calculadas (la web).
    """

    def __init__(self, mov, pms, pres, cfg, res=None):
        self.cfg = cfg
        self.apuntes = c.asignar_lineas(mov, cfg)
        self.det_real = self.apuntes.pivot_table(index=['Id hotel', 'Mes'], columns='Línea',
                                                 values='Importe sin IVA', aggfunc='sum').fillna(0.0)
        self.det_ppto = c.presupuesto_detalle(pres)
        self.act = c.actividad_completa(pms, cfg)
        self.cuadre = c.cuadre(mov, pms, cfg)
        self.ratios = c.comprobar_ratios(pms, cfg)
        res = res if res is not None else pd.DataFrame()
        self.res_agg = rv.agregar_por_mes(res)
        self.res_llegadas = rv.agregar_llegadas(res)
        a = self.apuntes.assign(Ceco=self.apuntes['Ceco'].replace('', '(sin ceco)'))
        self.apuntes_agg = a.groupby(['Id hotel', 'Mes', 'Línea', 'Bloque', 'Ceco', 'Proveedor'], as_index=False).agg(
            **{'Importe sin IVA': ('Importe sin IVA', 'sum'), 'Apuntes': ('Importe sin IVA', 'size')})
        self._fuente_desviaciones = lambda h, m: calcular_desviaciones(self.apuntes, self.det_real, self.det_ppto, self.act,
                                                                       self.cuadre, self.cfg, h, m)
        self._preparar()

    @classmethod
    def desde_precalculo(cls, tablas, cfg, fuente_desviaciones):
        d = cls.__new__(cls)
        d.cfg = cfg
        for k in CLAVES_PRECALCULO:
            setattr(d, k, tablas[k])
        d._fuente_desviaciones = fuente_desviaciones
        d._preparar()
        return d

    def tablas(self):
        """Lo que se guarda en el precálculo."""
        return {k: getattr(self, k) for k in CLAVES_PRECALCULO}

    def _preparar(self):
        cfg = self.cfg
        self.nombres = cfg['hoteles'].set_index('Id hotel')['Hotel'].to_dict()
        self.meses = sorted(set(self.act.index.get_level_values('Mes')) & set(self.det_real.index.get_level_values('Mes')),
                            reverse=True) if len(self.act) and len(self.det_real) else []
        self.cuadre_res = rv.cuadre_con_operador(self.res_agg, self.act, float(c.parametro(cfg, 'tolerancia_cuadre_eur'))) \
            if len(self.res_agg) else pd.DataFrame()
        self.canales = sorted(set(self.res_agg['Canal'])) if len(self.res_agg) else []
        self._filtrados = {}
        self._desviaciones = {}

    @property
    def hay_reservas(self):
        return len(self.res_agg) > 0

    def desviaciones(self, hotel, mes):
        """Desviaciones de un hotel y un mes (se calculan una vez y se guardan: no dependen de los filtros)."""
        if (hotel, mes) not in self._desviaciones:
            self._desviaciones[(hotel, mes)] = self._fuente_desviaciones(hotel, mes) if (hotel, mes) in self.det_real.index else []
        return self._desviaciones[(hotel, mes)]

    def resultados(self, hoteles, meses, cual='real'):
        det = self.det_real if cual == 'real' else self.det_ppto
        s = _suma(det, hoteles, meses)
        if s is None:
            return None
        fila = c.resultados(s.to_frame().T, self.cfg).iloc[0]
        return fila

    def actividad(self, hoteles, meses):
        return _suma(self.act, hoteles, meses)

    def kpis(self, hoteles, meses, cual='real'):
        res = self.resultados(hoteles, meses, cual)
        act = self.actividad(hoteles, meses)
        if res is None or act is None:
            return {}
        k = c.kpis(res, act, ppto=(cual == 'ppto'))
        k['Gastos operativos'] = float(res['Total consumos'] + res['Total personal'] + res['Total otros gastos operativos'])
        return k

    def por_mes(self, hoteles, meses, cual='real', desplazar=0):
        """KPIs mes a mes (una sola pasada de cálculo): {mes: kpis}. desplazar=12 da el año anterior."""
        orig = [m - pd.DateOffset(months=desplazar) for m in meses]
        det = _filas(self.det_real if cual == 'real' else self.det_ppto, hoteles, orig)
        act = _filas(self.act, hoteles, orig)
        if len(det) == 0 or len(act) == 0:
            return {}
        det_m = det.groupby(level='Mes').sum()
        act_m = act.groupby(level='Mes').sum()
        res_m = c.resultados(det_m, self.cfg)
        out = {}
        for m, o in zip(meses, orig):
            if o in res_m.index and o in act_m.index:
                k = c.kpis(res_m.loc[o], act_m.loc[o], ppto=(cual == 'ppto'))
                fila = res_m.loc[o]
                k['Gastos operativos'] = float(fila['Total consumos'] + fila['Total personal'] + fila['Total otros gastos operativos'])
                k['Alojamiento'] = float(act_m.loc[o, 'Alojamiento']) if cual == 'real' else None
                out[m] = k
        return out

    def det_filtrado(self, ceco=None, proveedor=None):
        """Detalle real por hotel, mes y línea con solo los apuntes de esos cecos o proveedores."""
        if not ceco and not proveedor:
            return self.det_real
        clave = (tuple(ceco or ()), tuple(proveedor or ()))
        if clave not in self._filtrados:
            a = self.apuntes_agg
            if ceco:
                a = a[a['Ceco'].isin(ceco)]
            if proveedor:
                a = a[a['Proveedor'].isin(proveedor)]
            self._filtrados[clave] = a.pivot_table(index=['Id hotel', 'Mes'], columns='Línea', values='Importe sin IVA',
                                                   aggfunc='sum').fillna(0.0) if len(a) else pd.DataFrame()
        return self._filtrados[clave]

    def reservas_mes(self, hoteles, meses, canal=None):
        return rv._sel(self.res_agg, hoteles, meses, canal) if self.hay_reservas else self.res_agg


# ---------------------------------------------------------------- textos de causas

def texto_causa(causa, referencia, nombre_visible):
    t = causa['tipo']
    if t == 'Cuadre':
        rel = nombre_visible(causa.get('hotel_relacionado'))
        cc = causa.get('causa_cuadre')
        if cc == 'contabilizado en otro hotel':
            return f'El operador lo reporta, pero en contabilidad está registrado en {rel}.'
        if cc == 'ingreso de otro hotel':
            return f'Incluye un ingreso de {rel} registrado en la contabilidad de este hotel.'
        if cc == 'abono no reportado por el operador':
            return f'Abono {causa.get("documento")} en contabilidad que el operador no reporta.'
        if cc == 'sin contabilizar':
            return f'El operador reporta {eur(abs(causa["importe"]))} que no están en contabilidad.'
        return f'Contabilidad registra {eur(abs(causa["importe"]))} que el operador no reporta.'
    if t == 'Actividad':
        partes = []
        if causa.get('var_cantidad') is not None:
            partes.append(f'{causa["cantidad"]} {con_signo(causa["var_cantidad"] * 100)}')
        if causa.get('var_precio') is not None:
            partes.append(f'{causa["precio"]} {con_signo(causa["var_precio"] * 100)}')
        return 'Se explica por la venta: ' + ' y '.join(partes) + f' frente al {referencia}.'
    if t == 'Ventas':
        return 'Variación de ventas. El operador y la contabilidad cuadran en esta línea.'
    if t == 'Falsa alarma':
        return f'Se explica por la actividad: {causa["unidad"]} {con_signo(causa["var_base"] * 100)} frente al {referencia}.'
    if t == 'Sin apuntes':
        return 'No hay ningún apunte este mes; el presupuesto reparte este gasto en todos los meses.'
    if t == 'Subida de precio' and causa.get('desde') is not None:
        return causa['texto'] + f', desde {MESES[causa["desde"].month - 1]}.'
    return causa.get('texto', '') + '.'


ETIQUETA_CAUSA = {
    'Cuadre': 'No cuadra', 'Actividad': 'Venta', 'Ventas': 'Venta', 'Falsa alarma': 'Falsa alarma',
    'Sin apuntes': 'Sin apuntes', 'Duplicada': 'Duplicada', 'Otro mes': 'Factura de otro mes',
    'Proveedor nuevo': 'Proveedor nuevo', 'Factura que falta': 'Factura que falta', 'Subida de precio': 'Subida de precio',
}
CAUSAS_DE_FACTURA = {'Duplicada', 'Otro mes', 'Proveedor nuevo', 'Factura que falta', 'Subida de precio', 'Cuadre'}


# ---------------------------------------------------------------- gráficos

def _cuota(v, total):
    return f'{pct(v / total)} del total' if total else ''


def _var_txt(v, ref, nombre_ref):
    if v is None or ref in (None, 0):
        return ''
    return f'{con_signo((v - ref) / abs(ref) * 100)} vs {nombre_ref}'


def _unir(*partes):
    return ' · '.join(p for p in partes if p)


def grafico(tipo, etiquetas, series, clic=None, **extra):
    """Un gráfico listo para dibujar: cada serie trae sus valores, el texto que va encima y el de la ayuda."""
    return {'tipo': tipo, 'etiquetas': etiquetas, 'series': series, 'clic': clic or [None] * len(etiquetas), **extra}


def serie(nombre, valores, textos=None, ayudas=None, color='principal', tipo=None, etiquetas_visibles=True, colores=None):
    """colores: opcional, un color por punto ('bien', 'mal'…) cuando el color dice si algo es bueno o malo."""
    limpio = [None if v is None or v != v else round(float(v), 4) for v in valores]
    return {'nombre': nombre, 'valores': limpio, 'textos': textos or [''] * len(limpio),
            'ayudas': ayudas or [''] * len(limpio), 'color': color, 'tipo': tipo, 'etiquetas_visibles': etiquetas_visibles,
            'colores': colores}


# ---------------------------------------------------------------- piezas del informe

def _pyg(datos, hoteles, periodo, periodo_aa):
    res = datos.resultados(hoteles, periodo)
    res_p = datos.resultados(hoteles, periodo, 'ppto')
    res_a = datos.resultados(hoteles, periodo_aa)
    filas = []
    for _, e in datos.cfg['estructura_informe'].iterrows():
        linea = e['Línea']
        if res is None or linea not in res.index:
            continue
        real = float(res[linea])
        ppto = float(res_p[linea]) if res_p is not None and linea in res_p.index else None
        aa = float(res_a[linea]) if res_a is not None and linea in res_a.index else None
        ingreso = e['Bloque'] in ('Ingresos',) or e['Tipo'] == 'Resultado'
        var = _variacion(real, ppto, 'rel', 1 if ingreso else -1) if ppto is not None else None
        filas.append({'linea': linea, 'tipo': e['Tipo'], 'bloque': e['Bloque'], 'real': eur(real), 'real_num': real,
                      'ppto': eur(ppto) if ppto is not None else '—', 'aa': eur(aa) if aa is not None else '—',
                      'dif': (con_signo(real - ppto, 0, '€') if ppto is not None else '—'),
                      'var': var, 'oculta': e['Tipo'] == 'Detalle',
                      'clic': {'tipo': 'facturas', 'linea': linea} if e['Tipo'] == 'Detalle' and linea != 'Reserva FF&E'
                      else ({'tipo': 'facturas', 'bloque': e['Bloque']} if e['Tipo'] == 'Subtotal' else None)})
    return res, res_p, filas


def _cuadre_filas(datos, hoteles, meses, nombre, nombre_visible, multimes):
    cfg = datos.cfg
    bloques = dict(zip(cfg['estructura_informe']['Línea'], cfg['estructura_informe']['Bloque']))
    filas, importe = [], 0.0
    for mes in meses:
        for h in hoteles:
            for linea in [l for l in c.lineas_detalle(cfg) if bloques.get(l) == 'Ingresos']:
                if (h, mes, linea) not in datos.cuadre.index:
                    continue
                q = datos.cuadre.loc[(h, mes, linea)]
                causa = ''
                if not q['Cuadra']:
                    importe += abs(float(q['Diferencia']))
                    causa = texto_causa({'tipo': 'Cuadre', 'causa_cuadre': q['Causa'], 'hotel_relacionado': q['Hotel relacionado'],
                                         'documento': q['Documento'], 'importe': -float(q['Diferencia'])}, 'presupuesto',
                                        nombre_visible)
                filas.append({'hotel': nombre(h), 'hotel_id': h, 'linea': linea, 'mes': mes_corto(mes), 'mes_id': f'{mes:%Y-%m}',
                              'operador': eur(q['Operador'], 2), 'contabilidad': eur(q['Contabilidad'], 2),
                              'diferencia': '0 €' if q['Cuadra'] else con_signo(q['Diferencia'], 2, '€'),
                              'dif_num': float(q['Diferencia']), 'cuadra': bool(q['Cuadra']), 'causa': causa,
                              'clic': {'tipo': 'facturas', 'linea': linea, 'mes': f'{mes:%Y-%m}', 'hotel': h}})
    filas.sort(key=lambda f: (f['cuadra'], f['mes_id'], f['hotel']))
    return filas, importe


def _ratios_filas(datos, hoteles, meses, nombre):
    rr = datos.ratios
    out = []
    if not len(rr):
        return out
    sel = rr[rr['Id hotel'].isin(hoteles) & rr['Mes'].isin(meses)]
    for _, x in sel.iterrows():
        puntos = x['Tipo'] == 'puntos'
        fmt = (lambda v: pct(v)) if x['Ratio'] in ('Ocupación', 'Captación de desayunos') else (lambda v: eur(v, 2))
        nota = x['Nota']
        if not x['Correcto'] and x['Impacto'] == x['Impacto'] and x['Impacto'] is not None:
            nota = f'Si se facturara como room nights × ADR del operador, el alojamiento saldría {eur(x["Impacto"])} más alto.'
        out.append({'hotel': nombre(x['Id hotel']), 'mes': mes_corto(x['Mes']), 'ratio': x['Ratio'], 'formula': x['Fórmula'],
                    'operador': fmt(x['Operador']), 'recalculado': fmt(x['Recalculado']),
                    'diferencia': con_signo(x['Diferencia'] * 100, 1, 'pp' if puntos else '%'),
                    'correcto': bool(x['Correcto']), 'nota': nota})
    out.sort(key=lambda f: f['correcto'])
    return out


def _desviaciones(datos, hoteles, meses, nombre, nombre_visible):
    cfg = datos.cfg
    desviaciones, falsas = [], []
    for mes in meses:
        desv = [d for h in hoteles for d in datos.desviaciones(h, mes)]
        for d in desv:
            referencia = d['Referencia']
            causas = d['Causas']
            textos = [{'etiqueta': ETIQUETA_CAUSA.get(x['tipo'], x['tipo']), 'texto': texto_causa(x, referencia, nombre_visible),
                       'proveedor': x.get('proveedor', ''), 'documento': x.get('documento', ''),
                       'importe': eur(x['importe']) if x['tipo'] in CAUSAS_DE_FACTURA else ''} for x in causas]
            if not textos:
                textos = [{'etiqueta': 'Sin causa', 'texto': 'Ninguna regla encuentra la causa en las facturas: revisar a mano.',
                           'proveedor': '', 'documento': '', 'importe': ''}]
            var = d['Var ppto'] if referencia == 'presupuesto' else d['Var AA']
            fila = {
                'hotel': nombre(d['Id hotel']), 'hotel_id': d['Id hotel'], 'linea': d['Línea'], 'ingreso': d['Ingreso'],
                'mes': mes_corto(mes), 'mes_id': f'{mes:%Y-%m}', 'mes_texto': mes_texto(mes),
                'real': eur(d['Real']), 'ppto': eur(d['Presupuesto']) if d['Presupuesto'] is not None else '—',
                'aa': eur(d['Año anterior']) if d['Año anterior'] is not None else '—',
                'dif': con_signo(d['Dif ref'], 0, '€'), 'dif_num': float(d['Dif ref']),
                'var': con_signo(var * 100, 1, '%') if var is not None else 'nuevo',
                'referencia': referencia, 'favorable': d['Favorable'], 'causas': textos,
                'tiene_causa_factura': any(x['tipo'] in CAUSAS_DE_FACTURA for x in causas),
                'sin_causa': not causas, 'impacto': abs(d['Dif ref']),
                'clic': {'tipo': 'facturas', 'linea': d['Línea'], 'mes': f'{mes:%Y-%m}', 'hotel': d['Id hotel']},
                'apuntes': d.get('Apuntes', []),
            }
            (falsas if d['Falsa alarma'] else desviaciones).append(fila)
    desviaciones.sort(key=lambda x: -x['impacto'])
    falsas.sort(key=lambda x: -x['impacto'])
    return desviaciones, falsas


def _alertas(cfg, diferencias, importe_dif, ratios_mal, desviaciones, estructural, es_grupo, p_txt):
    tol = c.parametro(cfg, 'tolerancia_cuadre_eur')
    umbral = f'{num(float(c.parametro(cfg, "umbral_desviacion_pct")) * 100)} % y {eur(c.parametro(cfg, "umbral_desviacion_eur"))}'
    alertas = []
    if len(diferencias) > 1:
        alertas.append({'prioridad': 1, 'impacto': 0, 'tipo': 'Cuadre', 'color': 'mal',
                        'que': f'{len(diferencias)} líneas de ingreso no cuadran',
                        'cuanto': f'{eur(importe_dif)} sumando las diferencias de cada línea',
                        'detalle': ' · '.join(f'{f["linea"]}' + (f' ({f["hotel"]})' if es_grupo else '') + f' {f["diferencia"]}'
                                              for f in diferencias[:6]),
                        'donde': 'Ingresos', 'umbral': f'tolerancia {eur(tol)}', 'periodo': p_txt, 'pagina': 'cuadre',
                        'hotel': ', '.join(sorted({f['hotel'] for f in diferencias})) if es_grupo else ''})
    for f in diferencias[:1] if len(diferencias) == 1 else []:
        alertas.append({'prioridad': 1, 'impacto': 0, 'tipo': 'Cuadre', 'color': 'mal',
                        'que': f'{f["linea"]} no cuadra' + (f' · {f["hotel"]}' if es_grupo else ''),
                        'cuanto': f'{f["diferencia"]} (operador {f["operador"]}, contabilidad {f["contabilidad"]})',
                        'detalle': f['causa'], 'donde': 'Ingresos', 'umbral': f'tolerancia {eur(tol)}', 'periodo': f['mes'],
                        'pagina': 'cuadre', 'hotel': f['hotel'] if es_grupo else ''})
    tol_r = f'tolerancia {num(float(c.parametro(cfg, "tolerancia_ratio_pct")) * 100, 1)} %'
    if len(ratios_mal) > 1:
        alertas.append({'prioridad': 2, 'impacto': 0, 'tipo': 'Ratio', 'color': 'aviso',
                        'que': f'{len(ratios_mal)} ratios del operador mal calculados',
                        'cuanto': ' · '.join(f'{x["ratio"]}' + (f' ({x["hotel"]})' if es_grupo else '') + f' {x["diferencia"]}'
                                             for x in ratios_mal[:6]),
                        'detalle': 'Revisar con el operador antes de usar sus ratios en ningún informe.',
                        'donde': 'Informe del operador', 'umbral': tol_r, 'periodo': p_txt, 'pagina': 'cuadre',
                        'hotel': ', '.join(sorted({x['hotel'] for x in ratios_mal})) if es_grupo else ''})
    for x in ratios_mal[:1] if len(ratios_mal) == 1 else []:
        alertas.append({'prioridad': 2, 'impacto': 0, 'tipo': 'Ratio', 'color': 'aviso',
                        'que': f'{x["ratio"]} del operador mal calculado' + (f' · {x["hotel"]}' if es_grupo else ''),
                        'cuanto': f'reporta {x["operador"]}, recalculado {x["recalculado"]} ({x["diferencia"]})',
                        'detalle': x['nota'], 'donde': 'Informe del operador', 'umbral': tol_r, 'periodo': x['mes'],
                        'pagina': 'cuadre', 'hotel': x['hotel'] if es_grupo else ''})
    for d in desviaciones:
        # Una desviación favorable solo es alerta si la explica una factura (p. ej. una factura que falta)
        if (d['favorable'] and not d['tiene_causa_factura']) or any(x['etiqueta'] == 'No cuadra' for x in d['causas']):
            continue
        alertas.append({'prioridad': 3 if d['tiene_causa_factura'] else 4, 'impacto': d['impacto'], 'tipo': 'Desviación',
                        'color': 'mal', 'que': f'{d["linea"]} {d["dif"]} frente al {d["referencia"]}' + (f' · {d["hotel"]}' if es_grupo else ''),
                        'cuanto': f'{d["var"]} (real {d["real"]})', 'detalle': d['causas'][0]['texto'],
                        'donde': d['linea'], 'umbral': umbral, 'periodo': f'{d["mes_texto"]} frente al {d["referencia"]}',
                        'pagina': 'desviaciones', 'clic': d['clic'], 'hotel': d['hotel'] if es_grupo else ''})
    for e in estructural:
        alertas.append({'prioridad': 4, 'impacto': 0, 'tipo': 'Comparativa', 'color': 'aviso',
                        'que': f'{e["linea"]} cara · {e["hotel"]}', 'cuanto': f'{e["valor"]} por room night frente a {e["mediana"]} en el resto',
                        'detalle': f'Unos {e["exceso"]} al mes por encima de los otros hoteles: coste estructural, no una factura puntual.',
                        'donde': e['linea'], 'umbral': '+20 % sobre la mediana de los otros hoteles', 'periodo': 'últimos 3 meses',
                        'pagina': 'comparativa', 'hotel': e['hotel']})
    alertas.sort(key=lambda a: (a['prioridad'], -a['impacto']))
    for a in alertas:   # nivel que ve el usuario y por el que filtra
        a['nivel'], a['nivel_txt'] = {1: ('p1', 'Urgente'), 2: ('p2', 'Revisar'), 3: ('p2', 'Revisar')}.get(a['prioridad'], ('p3', 'Vigilar'))
        a.setdefault('hotel', '')
    return alertas


# ---------------------------------------------------------------- informe completo

def construir(datos, hoteles_visibles, seleccion, mes, modo='mes', filtros=None):
    """Contenido de las páginas del informe.

    hoteles_visibles: los hoteles que el usuario puede ver (un director de hotel, solo el suyo).
    seleccion: 'GRUPO', un Id de hotel o una lista de Ids, siempre dentro de hoteles_visibles.
    mes: un mes, o una lista de meses (los que el usuario marca en el filtro de fechas).
    filtros: {'ceco': [...], 'proveedor': [...], 'canal': [...]} (opcional).
    """
    cfg = datos.cfg
    filtros = filtros or {}
    ceco, proveedor, canal = filtros.get('ceco') or [], filtros.get('proveedor') or [], filtros.get('canal') or []
    if seleccion == 'GRUPO':
        hoteles = list(hoteles_visibles)
    elif isinstance(seleccion, (list, tuple)):
        hoteles = [h for h in hoteles_visibles if h in seleccion] or list(hoteles_visibles)
    else:
        hoteles = [seleccion]
    es_grupo = len(hoteles) > 1
    periodo = _periodo(mes, modo)
    mes_ref = periodo[-1]
    periodo_aa = [m - pd.DateOffset(months=12) for m in periodo]
    nombre = lambda h: datos.nombres.get(h, h)
    nombre_visible = lambda h: nombre(h) if h in hoteles_visibles else 'otro hotel del grupo'
    p_txt = texto_periodo(periodo)

    k_real = datos.kpis(hoteles, periodo)
    k_ppto = datos.kpis(hoteles, periodo, 'ppto')
    k_aa = datos.kpis(hoteles, periodo_aa)
    hay_ppto = bool(k_ppto)

    # ---- mes a mes, solo los meses elegidos
    # Los gráficos de barras por mes enseñan siempre los 12 meses hasta el último mes elegido (decisión de Lara,
    # 13 nov 2026); los meses elegidos van en azul fuerte y el resto en azul claro. Las tarjetas suman solo lo elegido.
    meses_graf = [mes_ref - pd.DateOffset(months=i) for i in range(11, -1, -1)]
    real_m = datos.por_mes(hoteles, meses_graf)
    ppto_m = datos.por_mes(hoteles, meses_graf, 'ppto')
    aa_m = datos.por_mes(hoteles, meses_graf, desplazar=12)
    meses_g = [m for m in meses_graf if m in real_m]
    resaltar_elegidos = any(m not in periodo for m in meses_g)
    colores_elegidos = ['principal' if m in periodo else 'comparacion' for m in meses_g] if resaltar_elegidos else None
    etiquetas = [mes_corto(m) for m in meses_g]
    clic_mes = [{'mes': f'{m:%Y-%m}'} for m in meses_g]
    g = lambda d, m, k: (d.get(m) or {}).get(k)
    total_ing = sum(g(real_m, m, 'Ingresos totales') or 0 for m in meses_g if m in periodo)

    def ayuda_mes(m, clave, formato_fn, extra=''):
        v = g(real_m, m, clave)
        return _unir(f'{formato_fn(v)}', extra, _var_txt(v, g(aa_m, m, clave), 'año anterior'),
                     _var_txt(v, g(ppto_m, m, clave), 'presupuesto'))

    g_resultado_mes = grafico('barras', etiquetas, [
        serie('Ingresos', [g(real_m, m, 'Ingresos totales') for m in meses_g],
              [corto(g(real_m, m, 'Ingresos totales')) for m in meses_g],
              [ayuda_mes(m, 'Ingresos totales', eur) for m in meses_g],
              'principal'),
        serie('Gastos operativos', [g(real_m, m, 'Gastos operativos') for m in meses_g],
              [corto(g(real_m, m, 'Gastos operativos')) for m in meses_g],
              [_unir(eur(g(real_m, m, 'Gastos operativos')),
                     f'{pct((g(real_m, m, "Gastos operativos") or 0) / g(real_m, m, "Ingresos totales"))} de los ingresos'
                     if g(real_m, m, 'Ingresos totales') else '',
                     _var_txt(g(real_m, m, 'Gastos operativos'), g(ppto_m, m, 'Gastos operativos'), 'presupuesto'))
               for m in meses_g], 'gasto'),
        serie('GOP', [g(real_m, m, 'GOP') for m in meses_g],
              [corto(g(real_m, m, 'GOP')) for m in meses_g],
              [_unir(eur(g(real_m, m, 'GOP')), f'{pct(g(real_m, m, "% GOP"))} de margen',
                     _var_txt(g(real_m, m, 'GOP'), g(aa_m, m, 'GOP'), 'año anterior'),
                     _var_txt(g(real_m, m, 'GOP'), g(ppto_m, m, 'GOP'), 'presupuesto')) for m in meses_g], 'resultado'),
    ], [{'tipo': 'calculo', 'que': 'gop', **x} for x in clic_mes], formato='eur')

    def real_ppto_aa(clave, nombre, que, extra_ayuda=None):
        """Real en barras de un solo color; presupuesto en línea y año anterior en línea discontinua (diseño 3b)."""
        reales = [g(real_m, m, clave) for m in meses_g]
        series = [serie(nombre, reales, [corto(v) for v in reales],
                        [_unir(ayuda_mes(m, clave, eur), extra_ayuda(m) if extra_ayuda else '') for m in meses_g], 'principal',
                        colores=colores_elegidos)]
        if any(g(ppto_m, m, clave) is not None for m in meses_g):
            series.append(serie('Presupuesto', [g(ppto_m, m, clave) for m in meses_g], None,
                                [_unir(f'Presupuesto {eur(g(ppto_m, m, clave))}', _var_txt(g(real_m, m, clave), g(ppto_m, m, clave), 'presupuesto'))
                                 for m in meses_g], 'ppto', tipo='line', etiquetas_visibles=False))
        if any(g(aa_m, m, clave) is not None for m in meses_g):
            series.append(serie('Año anterior', [g(aa_m, m, clave) for m in meses_g], None,
                                [_unir(f'Año anterior {eur(g(aa_m, m, clave))}', _var_txt(g(real_m, m, clave), g(aa_m, m, clave), 'año anterior'))
                                 for m in meses_g], 'aa', tipo='line', etiquetas_visibles=False))
        return grafico('barras', etiquetas, series, [{'tipo': 'calculo', 'que': que, **x} for x in clic_mes], formato='eur')

    g_gop_mes = real_ppto_aa('GOP', 'GOP', 'gop', lambda m: f'{pct(g(real_m, m, "% GOP"))} de margen')
    g_ingresos_mes = real_ppto_aa('Ingresos totales', 'Ingresos', 'ingresos')

    g_ocupacion_mes = grafico('barras', etiquetas, [
        serie('Ocupación', [(g(real_m, m, 'Ocupación') or 0) * 100 for m in meses_g],
              [pct(g(real_m, m, 'Ocupación')) for m in meses_g],
              [_unir(pct(g(real_m, m, 'Ocupación')), f'{num(g(real_m, m, "Room nights"))} room nights',
                     f'ADR {eur(g(real_m, m, "ADR"), 2)}', f'RevPAR {eur(g(real_m, m, "RevPAR"), 2)}',
                     (f'{con_signo(((g(real_m, m, "Ocupación") or 0) - g(aa_m, m, "Ocupación")) * 100, 1, "pp")} vs año anterior'
                      if g(aa_m, m, 'Ocupación') is not None else '')) for m in meses_g], 'principal', colores=colores_elegidos),
        serie('Ocupación año anterior', [(g(aa_m, m, 'Ocupación') or 0) * 100 if g(aa_m, m, 'Ocupación') is not None else None
                                         for m in meses_g],
              [pct(g(aa_m, m, 'Ocupación')) if g(aa_m, m, 'Ocupación') is not None else '' for m in meses_g],
              [_unir(pct(g(aa_m, m, 'Ocupación')), f'{num(g(aa_m, m, "Room nights"))} room nights',
                     f'ADR {eur(g(aa_m, m, "ADR"), 2)}') if g(aa_m, m, 'Ocupación') is not None else '' for m in meses_g],
              'aa', tipo='line'),
    ], [{'tipo': 'reservas', **x} for x in clic_mes], formato='pct')

    g_adr_mes = grafico('lineas', etiquetas, [
        serie('ADR', [g(real_m, m, 'ADR') for m in meses_g], [eur(g(real_m, m, 'ADR'), 2) for m in meses_g],
              [_unir(eur(g(real_m, m, 'ADR'), 2), f'{eur(g(real_m, m, "Alojamiento"))} de alojamiento',
                     f'{num(g(real_m, m, "Room nights"))} room nights', _var_txt(g(real_m, m, 'ADR'), g(aa_m, m, 'ADR'), 'año anterior'))
               for m in meses_g], 'principal'),
        serie('RevPAR', [g(real_m, m, 'RevPAR') for m in meses_g], [eur(g(real_m, m, 'RevPAR'), 2) for m in meses_g],
              [_unir(eur(g(real_m, m, 'RevPAR'), 2), f'ocupación {pct(g(real_m, m, "Ocupación"))}',
                     _var_txt(g(real_m, m, 'RevPAR'), g(aa_m, m, 'RevPAR'), 'año anterior')) for m in meses_g], 'comparacion'),
    ], [{'tipo': 'reservas', **x} for x in clic_mes], formato='eur2')

    # ---- cuenta de resultados del periodo
    res, res_p, pyg = _pyg(datos, hoteles, periodo, periodo_aa)
    cascada = []
    if res is not None:
        pasos = [('Ingresos', float(res['Total ingresos']), True, 'Ingresos'),
                 ('Consumos', -float(res['Total consumos']), False, 'Consumos'),
                 ('Personal', -float(res['Total personal']), False, 'Personal'),
                 ('Otros gastos', -float(res['Total otros gastos operativos']), False, 'Otros gastos operativos'),
                 ('GOP', float(res['GOP']), True, None), ('Ajustes', -float(res['Total ajustes']), False, 'Ajustes'),
                 ('AGOP', float(res['AGOP']), True, None),
                 ('Bajo AGOP', -float(res['Total por debajo del AGOP']), False, 'Bajo AGOP'), ('GOP2', float(res['GOP2']), True, None)]
        ingresos_tot = float(res['Total ingresos']) or None
        cascada = grafico('cascada', [p[0] for p in pasos], [serie(
            'Cuenta de resultados', [p[1] for p in pasos], [corto(p[1]) for p in pasos],
            [_unir(eur(p[1]), f'{pct(abs(p[1]) / ingresos_tot)} de los ingresos' if ingresos_tot else '') for p in pasos])],
            [{'tipo': 'facturas', 'bloque': p[3]} if p[3] else None for p in pasos], totales=[p[2] for p in pasos],
            formato='eur')

    # ---- gastos por partida (filtrables por ceco y proveedor)
    det_f = datos.det_filtrado(ceco, proveedor)
    s_f = _suma(det_f, hoteles, periodo) if len(det_f) else None
    s_p = _suma(datos.det_ppto, hoteles, periodo) if len(datos.det_ppto) and not (ceco or proveedor) else None
    est = cfg['estructura_informe']
    bloques = dict(zip(est['Línea'], est['Bloque']))
    partidas = [l for l in c.lineas_detalle(cfg)
                if bloques.get(l) in ('Consumos', 'Personal', 'Otros gastos operativos', 'Ajustes', 'Bajo AGOP')]
    gastos = []
    if s_f is not None:
        for l in partidas:
            v = float(s_f.get(l, 0.0))
            p = float(s_p[l]) if s_p is not None and l in s_p.index else None
            if abs(v) > 0.5 or (p and abs(p) > 0.5):
                gastos.append((l, v, p))
    gastos.sort(key=lambda x: -abs(x[1]))
    total_gastos = sum(x[1] for x in gastos)
    gastos = gastos[:MAX_PARTIDAS_GRAFICO]   # las mayores; el resto está en la tabla de la cuenta de resultados
    g_gastos = grafico('barras_h', [x[0] for x in gastos], [
        serie('Real', [x[1] for x in gastos], [corto(x[1]) for x in gastos],
              [_unir(eur(x[1]), f'{pct(x[1] / total_gastos)} de los gastos' if total_gastos else '',
                     f'presupuesto {eur(x[2])} ({con_signo((x[1] - x[2]) / abs(x[2]) * 100)})' if x[2] else '')
               for x in gastos], 'gasto'),
    ] + ([serie('Presupuesto', [x[2] for x in gastos], [corto(x[2]) if x[2] is not None else '' for x in gastos],
                [_unir(f'presupuesto {eur(x[2])}', f'real {eur(x[1])}') if x[2] is not None else '' for x in gastos],
                'comparacion', etiquetas_visibles=False)] if s_p is not None else []),
        [{'tipo': 'facturas', 'linea': x[0]} for x in gastos], formato='eur')

    # ---- ingresos por departamento
    ingresos_l = [x for x in pyg if x['bloque'] == 'Ingresos' and x['tipo'] == 'Detalle' and abs(x['real_num']) > 0.5]
    ingresos_l.sort(key=lambda x: -x['real_num'])
    g_departamentos = grafico('barras_h', [x['linea'] for x in ingresos_l], [
        serie('Ingresos', [x['real_num'] for x in ingresos_l], [corto(x['real_num']) for x in ingresos_l],
              [_unir(x['real'], _cuota(x['real_num'], total_ing), f'presupuesto {x["ppto"]}' if x['ppto'] != '—' else '')
               for x in ingresos_l], 'principal')],
        [{'tipo': 'facturas', 'linea': x['linea']} for x in ingresos_l], formato='eur')

    # ---- reservas: canales, perfil y cuadre con el operador
    canales_tabla, g_canales, g_segmentos, g_paises, k_res, k_res_aa = [], None, None, None, {}, {}
    if datos.hay_reservas:
        tabla = rv.por_canal(datos.res_agg, datos.res_llegadas, hoteles, periodo, canal)
        k_res = rv.kpis_reservas(datos.res_agg, datos.res_llegadas, hoteles, periodo, canal)
        k_res_aa = rv.kpis_reservas(datos.res_agg, datos.res_llegadas, hoteles, periodo_aa, canal)
        if len(tabla):
            canales_tabla = [{'canal': x['Canal'], 'tipo': x['Tipo de canal'], 'reservas': num(x['Reservas']),
                              'noches': num(x['Noches']), 'pct_noches': pct(x['% noches']), 'ingresos': eur(x['Ingresos']),
                              'pct_ingresos': pct(x['% ingresos']), 'adr': eur(x['ADR'], 2),
                              'antelacion': num(x['Antelación media (días)']) + ' días',
                              'cancelacion': pct(x['% cancelación']),
                              'clic': {'tipo': 'reservas', 'canal_sel': x['Canal']}} for _, x in tabla.iterrows()]
            g_canales = grafico('barras_h', list(tabla['Canal']), [
                serie('Noches', list(tabla['Noches']), [num(v) for v in tabla['Noches']],
                      [_unir(f'{num(x["Noches"])} noches', f'{pct(x["% noches"])} de las noches', eur(x['Ingresos']),
                             f'ADR {eur(x["ADR"], 2)}', f'{num(x["Reservas"])} reservas') for _, x in tabla.iterrows()],
                      'principal')],
                [{'tipo': 'reservas', 'canal_sel': c_} for c_ in tabla['Canal']], formato='num')
        m = datos.reservas_mes(hoteles, periodo, canal)
        if len(m):
            def reparto(col, top=8):
                t = m.groupby(col)['Noches'].sum().sort_values(ascending=False)
                if len(t) > top:
                    t = pd.concat([t.iloc[:top - 1], pd.Series({'Otros': t.iloc[top - 1:].sum()})])
                tot = t.sum()
                return t, tot
            seg, tot = reparto('Segmento')
            g_segmentos = grafico('donut', list(seg.index), [serie('Noches', list(seg.values), [pct(v / tot) for v in seg.values],
                                  [_unir(f'{num(v)} noches', f'{pct(v / tot)} del total') for v in seg.values], 'principal')],
                                  [{'tipo': 'reservas', 'segmento': s_} if s_ != 'Otros' else None for s_ in seg.index],
                                  formato='num')
            pais, tot = reparto('Nacionalidad')
            g_paises = grafico('barras_h', list(pais.index), [serie('Noches', list(pais.values), [pct(v / tot) for v in pais.values],
                               [_unir(f'{num(v)} noches', f'{pct(v / tot)} del total') for v in pais.values], 'principal')],
                               [{'tipo': 'reservas', 'nacionalidad': p_} if p_ != 'Otros' else None for p_ in pais.index],
                               formato='num')

    cuadre_reservas = []
    if len(datos.cuadre_res):
        q = datos.cuadre_res
        sel = q[q.index.get_level_values('Id hotel').isin(hoteles) & q.index.get_level_values('Mes').isin(periodo)]
        for (h, m_), x in sel.iterrows():
            cuadre_reservas.append({'hotel': nombre(h), 'mes': mes_corto(m_), 'noches_res': num(x['Noches reservas']),
                                    'noches_op': num(x['Noches operador']), 'dif_noches': con_signo(x['Dif. noches'], 0, ''),
                                    'ing_res': eur(x['Ingresos reservas'], 2), 'ing_op': eur(x['Ingresos operador'], 2),
                                    'dif_ing': '0 €' if abs(x['Dif. ingresos']) < 0.005 else con_signo(x['Dif. ingresos'], 2, '€'),
                                    'cuadra': bool(x['Cuadra']),
                                    'clic': {'tipo': 'reservas', 'mes': f'{m_:%Y-%m}', 'hotel': h}})
        cuadre_reservas.sort(key=lambda f: f['cuadra'])

    # ---- cuadre y ratios (todos los meses elegidos)
    cuadre_filas, importe_dif = _cuadre_filas(datos, hoteles, periodo, nombre, nombre_visible, len(periodo) > 1)
    diferencias = [f for f in cuadre_filas if not f['cuadra']]
    g_cuadre = grafico('barras_h', [f'{f["linea"]} · {f["hotel"]}' + (f' · {f["mes"]}' if len(periodo) > 1 else '')
                                    for f in diferencias],
                       [serie('Diferencia', [f['dif_num'] for f in diferencias], [f['diferencia'] for f in diferencias],
                              [_unir(f'operador {f["operador"]}', f'contabilidad {f["contabilidad"]}', f['causa']) for f in diferencias],
                              'gasto', colores=['mal'] * len(diferencias))], [f['clic'] for f in diferencias], formato='eur') if diferencias else None
    ratios = _ratios_filas(datos, hoteles, periodo, nombre)
    ratios_mal = [x for x in ratios if not x['correcto']]

    # ---- desviaciones (todos los meses elegidos)
    desviaciones, falsas = _desviaciones(datos, hoteles, periodo, nombre, nombre_visible)
    top_desv = desviaciones[:12]
    g_desviaciones = grafico('barras_h', [f'{d["linea"]} · {d["hotel"]}' + (f' · {d["mes"]}' if len(periodo) > 1 else '')
                                          for d in top_desv],
                             [serie('Diferencia', [d['dif_num'] for d in top_desv], [d['dif'] for d in top_desv],
                                    [_unir(f'{d["dif"]} ({d["var"]}) frente al {d["referencia"]}', f'real {d["real"]}',
                                           d['causas'][0]['etiqueta'] + ': ' + d['causas'][0]['texto']) for d in top_desv],
                                    'divergente', colores=['bien' if d['favorable'] else 'mal' for d in top_desv])], [d['clic'] for d in top_desv], formato='eur') if top_desv else None

    # ---- comparativa entre hoteles
    comparativa, estructural, g_hoteles, g_comparativa_margen = [], [], None, None
    if es_grupo:
        filas_h = []
        for h in hoteles:
            k = datos.kpis([h], periodo)
            kp = datos.kpis([h], periodo, 'ppto')
            if not k:
                continue
            filas_h.append((h, k))
            dif_h = sum(1 for f in diferencias if f['hotel_id'] == h)
            comparativa.append({'id': h, 'hotel': nombre(h), 'ingresos': eur(k['Ingresos totales']), 'gop': eur(k['GOP']),
                                'gop_pct': pct(k['% GOP']), 'ocupacion': pct(k['Ocupación']), 'adr': eur(k['ADR'], 2),
                                'revpar': eur(k['RevPAR'], 2), 'labor': pct(k['Labor cost']), 'cpor': eur(k['CPOR'], 2),
                                'gop_vs_ppto': _variacion(k['GOP'], kp.get('GOP') if kp else None, 'rel', 1),
                                'cuadre': dif_h,
                                'desviaciones': sum(1 for x in desviaciones if x['hotel_id'] == h and not x['favorable'])})
        total_gop = sum(k['GOP'] or 0 for _, k in filas_h)
        g_hoteles = grafico('barras_h', [nombre(h) for h, _ in filas_h], [
            serie('GOP', [k['GOP'] for _, k in filas_h], [corto(k['GOP']) for _, k in filas_h],
                  [_unir(eur(k['GOP']), f'{pct(k["% GOP"])} de margen', _cuota(k['GOP'], total_gop),
                         f'ingresos {eur(k["Ingresos totales"])}', f'ocupación {pct(k["Ocupación"])}') for _, k in filas_h],
                  'resultado')], [{'tipo': 'hotel', 'hotel': h} for h, _ in filas_h], formato='eur')
        g_comparativa = grafico('barras', [nombre(h) for h, _ in filas_h], [
            serie('% GOP', [(k['% GOP'] or 0) * 100 for _, k in filas_h], [pct(k['% GOP']) for _, k in filas_h],
                  [_unir(f'{pct(k["% GOP"])} de margen', f'GOP {eur(k["GOP"])}') for _, k in filas_h], 'resultado'),
            serie('Ocupación', [(k['Ocupación'] or 0) * 100 for _, k in filas_h], [pct(k['Ocupación']) for _, k in filas_h],
                  [_unir(pct(k['Ocupación']), f'{num(k["Room nights"])} room nights') for _, k in filas_h], 'principal'),
            serie('Labor cost', [(k['Labor cost'] or 0) * 100 for _, k in filas_h], [pct(k['Labor cost']) for _, k in filas_h],
                  [_unir(f'{pct(k["Labor cost"])} de los ingresos en personal') for _, k in filas_h], 'gasto'),
        ], [{'tipo': 'hotel', 'hotel': h} for h, _ in filas_h], formato='pct')
        cp = r.coste_por_room_night(datos.det_real, datos.act, cfg, hoteles, mes_ref)
        if len(cp):
            for _, x in cp[cp['Alto']].iterrows():
                estructural.append({'hotel': nombre(x['Id hotel']), 'linea': x['Línea'],
                                    'valor': eur(x['Por room night'], 2), 'mediana': eur(x['Mediana otros'], 2),
                                    'exceso': eur(x['Exceso'])})
    else:
        # Un solo hotel (diseño 3d): lo que con varios hoteles compara hoteles, aquí compara los últimos 12 meses
        # del hotel con su presupuesto y con el año anterior. Lee los mismos resultados precalculados.
        doce = [mes_ref - pd.DateOffset(months=i) for i in range(11, -1, -1)]
        r12, p12 = datos.por_mes(hoteles, doce), datos.por_mes(hoteles, doce, 'ppto')
        a12 = datos.por_mes(hoteles, doce, desplazar=12)
        m12 = [m for m in doce if m in r12]
        v = lambda d, m, k: (d.get(m) or {}).get(k)
        for m in reversed(m12):
            k = r12[m]
            comparativa.append({'mes': mes_texto(m), 'mes_id': f'{m:%Y-%m}', 'ingresos': eur(k['Ingresos totales']),
                                'gop': eur(k['GOP']), 'gop_pct': pct(k['% GOP']),
                                'gop_vs_ppto': _variacion(k['GOP'], v(p12, m, 'GOP'), 'rel', 1),
                                'gop_vs_aa': _variacion(k['GOP'], v(a12, m, 'GOP'), 'rel', 1),
                                'ocupacion': pct(k['Ocupación']), 'ocu_vs_aa': _variacion(k['Ocupación'], v(a12, m, 'Ocupación'), 'pp', 1),
                                'adr': eur(k['ADR'], 2), 'revpar': eur(k['RevPAR'], 2), 'labor': pct(k['Labor cost']),
                                'cpor': eur(k['CPOR'], 2)})
        et12 = [mes_corto(m) for m in m12]
        clic12 = [{'tipo': 'calculo', 'que': 'gop', 'mes': f'{m:%Y-%m}'} for m in m12]
        series12 = [serie('GOP', [v(r12, m, 'GOP') for m in m12], [corto(v(r12, m, 'GOP')) for m in m12],
                          [_unir(eur(v(r12, m, 'GOP')), f'{pct(v(r12, m, "% GOP"))} de margen',
                                 _var_txt(v(r12, m, 'GOP'), v(p12, m, 'GOP'), 'presupuesto'),
                                 _var_txt(v(r12, m, 'GOP'), v(a12, m, 'GOP'), 'año anterior')) for m in m12], 'principal')]
        if any(v(p12, m, 'GOP') is not None for m in m12):
            series12.append(serie('Presupuesto', [v(p12, m, 'GOP') for m in m12], None,
                                  [f'Presupuesto {eur(v(p12, m, "GOP"))}' for m in m12], 'ppto', tipo='line', etiquetas_visibles=False))
        if any(v(a12, m, 'GOP') is not None for m in m12):
            series12.append(serie('Año anterior', [v(a12, m, 'GOP') for m in m12], None,
                                  [f'Año anterior {eur(v(a12, m, "GOP"))}' for m in m12], 'aa', tipo='line', etiquetas_visibles=False))
        g_hoteles = None
        g_comparativa = grafico('barras', et12, series12, clic12, formato='eur')
        g_comparativa_margen = grafico('barras', et12, [
            serie('% GOP', [(v(r12, m, '% GOP') or 0) * 100 for m in m12], [pct(v(r12, m, '% GOP')) for m in m12],
                  [_unir(f'{pct(v(r12, m, "% GOP"))} de margen') for m in m12], 'resultado'),
            serie('% GOP año anterior', [(v(a12, m, '% GOP') * 100) if v(a12, m, '% GOP') is not None else None for m in m12], None,
                  [f'{pct(v(a12, m, "% GOP"))} el año anterior' if v(a12, m, '% GOP') is not None else '' for m in m12],
                  'aa', tipo='line', etiquetas_visibles=False),
            serie('Labor cost', [(v(r12, m, 'Labor cost') or 0) * 100 for m in m12], [pct(v(r12, m, 'Labor cost')) for m in m12],
                  [_unir(f'{pct(v(r12, m, "Labor cost"))} de los ingresos en personal') for m in m12], 'gasto'),
        ], clic12, formato='pct')

    alertas = _alertas(cfg, diferencias, importe_dif, ratios_mal, desviaciones, estructural, es_grupo, p_txt)

    # ---- tarjetas
    def tarjeta_simple(nombre_t, valor, formula, var_aa=None):
        return {'nombre': nombre_t, 'valor': valor, 'formula': formula, 'ppto': False, 'aa': var_aa}  # sin presupuesto: no aplica
    tarjetas_reservas = []
    if k_res:
        tarjetas_reservas = [
            tarjeta_simple('Reservas', num(k_res['Reservas']), 'Reservas con estancia en el periodo (por fecha de llegada)',
                           _variacion(k_res['Reservas'], k_res_aa.get('Reservas'), 'rel', 1)),
            tarjeta_simple('% cancelación', pct(k_res['% cancelación']), 'Canceladas / (con estancia + canceladas). Subir es malo',
                           _variacion(k_res['% cancelación'], k_res_aa.get('% cancelación'), 'pp', -1)),
            tarjeta_simple('% venta directa', pct(k_res['% directo']), 'Noches de canales directos / total de noches',
                           _variacion(k_res['% directo'], k_res_aa.get('% directo'), 'pp', 1)),
            tarjeta_simple('Estancia media', f'{num(k_res["Estancia media"], 1)} noches', 'Noches por reserva',
                           _variacion(k_res['Estancia media'], k_res_aa.get('Estancia media'), 'rel', 1)),
        ]

    titulo = 'Todo el grupo' if len(hoteles) == len(hoteles_visibles) and es_grupo else ', '.join(nombre(h) for h in hoteles)
    habitaciones = int(cfg['hoteles'].set_index('Id hotel').loc[hoteles, 'Habitaciones'].sum())
    return {
        'titulo': titulo, 'es_grupo': es_grupo, 'habitaciones': habitaciones, 'hoteles': hoteles,
        'mes': mes_ref, 'meses': periodo, 'mes_texto': mes_texto(mes_ref), 'modo': modo,
        'periodo_texto': p_txt, 'varios_meses': len(periodo) > 1,
        'hay_ppto': hay_ppto, 'hay_aa': bool(k_aa), 'hay_reservas': datos.hay_reservas,
        'filtro_gastos': bool(ceco or proveedor), 'filtro_canal': bool(canal),
        'tarjetas_resumen': tarjetas('resumen', k_real, k_ppto, k_aa),
        'franja': franja_presupuesto(k_real, k_ppto, k_aa),
        'hoteles_nombres': [nombre(h) for h in hoteles],
        'tarjetas_ocupacion': tarjetas('ocupacion', k_real, k_ppto, k_aa),
        'tarjetas_reservas': tarjetas_reservas,
        'tarjetas_cuenta': tarjetas('cuenta', k_real, k_ppto, k_aa),
        'tarjetas_portada': tarjetas('portada', k_real, k_ppto, k_aa),
        'graficos': {
            'resultado_mes': g_resultado_mes, 'gop_mes': g_gop_mes, 'ingresos_mes': g_ingresos_mes, 'ocupacion_mes': g_ocupacion_mes, 'adr_mes': g_adr_mes,
            'cascada': cascada, 'gastos': g_gastos, 'departamentos': g_departamentos, 'hoteles': g_hoteles,
            'canales': g_canales, 'segmentos': g_segmentos, 'paises': g_paises,
            'cuadre': g_cuadre, 'desviaciones': g_desviaciones, 'comparativa': g_comparativa, 'comparativa_margen': g_comparativa_margen,
        },
        'pyg': pyg, 'canales': canales_tabla, 'cuadre_reservas': cuadre_reservas,
        'cuadre_reservas_mal': [x for x in cuadre_reservas if not x['cuadra']],
        'cuadre': cuadre_filas, 'diferencias': diferencias, 'importe_diferencias': eur(importe_dif),
        'ratios': ratios, 'ratios_mal': ratios_mal,
        'desviaciones': desviaciones, 'falsas_alarmas': falsas,
        'comparativa': comparativa, 'estructural': estructural,
        'alertas': alertas[:MAX_ALERTAS_PORTADA], 'todas_alertas': alertas, 'total_alertas': len(alertas),
    }
