"""Cuádralo · revisión de archivos con cosas desconocidas.

Antes de normalizar, se mira cada archivo nuevo y se apunta todo lo que la configuración de la empresa no conoce:
columnas renombradas o nuevas, hoteles y fincas, cuentas contables, canales de reserva, hojas y año del presupuesto.
Cada cosa se convierte en una pregunta con sus opciones. Las sugerencias las pone cuadralo/sugerencias.py
(parecido de nombres o Azure OpenAI) y la respuesta la confirma una persona en la web: nada se usa sin su OK.

Lo confirmado se guarda como mapeo de la empresa y aplicar_mapeos() lo añade a la configuración, así que la
próxima vez ya no se pregunta.
"""
import re
from datetime import date

import pandas as pd

from cuadralo import normalizar as N

CLASES = {
    'columna': 'Columna', 'hotel': 'Hotel', 'finca': 'Finca', 'cuenta': 'Cuenta contable',
    'canal': 'Canal de reserva', 'hoja': 'Hoja del presupuesto', 'anio': 'Año del presupuesto',
}


def _texto(v):
    return '' if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _muestras(serie, n=3):
    vals = [_texto(v) for v in serie.dropna().unique()[:n]]
    return [v[:60] for v in vals if v]


def _opciones_hoteles(cfg):
    return [[h, f'{h} · {n}'] for h, n in zip(cfg['hoteles']['Id hotel'], cfg['hoteles']['Hotel'])]


def _p(clase, tipo, archivo, clave, texto, opciones, muestras=None, modo='nueva'):
    return {'clase': clase, 'tipo': tipo, 'archivo': archivo, 'clave': str(clave), 'texto': texto,
            'opciones': [[str(v), str(e)] for v, e in opciones], 'muestras': muestras or [], 'modo': modo}


def _operador(nombre, archivo, cfg):
    preguntas = []
    df, _ = N.leer_con_cabecera(archivo, 'Hotel')
    alias = N.alias_columnas(cfg, 'operador')
    df = N._aplicar_alias(df, alias)
    conocidas = list(dict.fromkeys(cfg['conceptos_pms']['Columna del operador']))
    nuevas = [c for c in df.columns if c != 'Hotel' and c not in conocidas]
    libres = [c for c in conocidas if c not in df.columns]
    for c in nuevas:
        preguntas.append(_p('columna', 'operador', nombre, c,
                            f'Columna «{c}»: ¿qué dato del informe del operador es?',
                            [[x, x] for x in libres] + [[N.IGNORAR, 'No usar esta columna']], _muestras(df[c])))
    ids = N.hotel_ids(cfg)
    for h in sorted({_texto(x) for x in df['Hotel'].dropna()} - set(ids)):
        preguntas.append(_p('hotel', 'operador', nombre, h, f'Hotel «{h}»: ¿a cuál de tus hoteles corresponde?',
                            _opciones_hoteles(cfg)))
    return preguntas


def _faltan(tipo, nombre, df, obligatorias, ya_usadas):
    libres = [c for c in df.columns if c not in obligatorias and c not in ya_usadas]
    out = []
    for campo in [c for c in obligatorias if c not in df.columns]:
        out.append(_p('columna', tipo, nombre, campo, f'No encuentro la columna «{campo}»: ¿cuál de las del archivo es?',
                      [[c, f'{c}  (p. ej. {", ".join(_muestras(df[c], 2)) or "vacía"})'] for c in libres],
                      modo='falta'))
    return out


def _business_central(nombre, archivo, cfg):
    alias = N.alias_columnas(cfg, 'business_central')
    raw = pd.read_excel(archivo, header=None, engine=N.MOTOR_EXCEL)
    fila = N.fila_cabecera(raw, set(N.COLUMNAS_BC) | set(alias))
    if fila is None:
        return []   # no parece un export de Business Central: lo dirá la normalización
    df = raw.iloc[fila + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[fila].tolist()]
    df = N._aplicar_alias(df.dropna(how='all'), alias)
    preguntas = _faltan('business_central', nombre, df, N.COLUMNAS_BC, set(alias))
    if 'Cód. dimensión 1 (FINCA)' in df.columns:
        conocidas = set(cfg['hoteles']['Finca']) | set((cfg.get('alias_finca') or {}))
        for f in sorted({_texto(x) for x in df['Cód. dimensión 1 (FINCA)'].dropna()} - conocidas):
            preguntas.append(_p('finca', 'business_central', nombre, f,
                                f'Finca «{f}» de contabilidad: ¿a qué hotel corresponde?', _opciones_hoteles(cfg)))
    if 'Nº cuenta' in df.columns:
        plan = set(cfg['plan_cuentas']['Cuenta contable'].astype(str))
        est = cfg['estructura_informe']
        lineas = est[est['Tipo'] == 'Detalle'][['Línea', 'Bloque']].drop_duplicates()
        opciones = [[l, f'{l} ({b})'] for l, b in zip(lineas['Línea'], lineas['Bloque'])]
        cuentas = df['Nº cuenta'].astype(str).str.replace(r'\.0$', '', regex=True)
        for c in sorted(set(cuentas.dropna()) - plan - {'nan', ''}):
            filas = df[cuentas == c]
            textos = []
            for col in ('Nombre cuenta', 'Descripción', 'Nombre origen'):
                if col in filas.columns:
                    textos += _muestras(filas[col], 2)
            preguntas.append(_p('cuenta', 'business_central', nombre, c,
                                f'Cuenta contable {c}: ¿en qué línea de la cuenta de resultados va?', opciones, textos))
    return preguntas


def _presupuesto(nombre, archivo, cfg):
    preguntas = []
    if N.anio_presupuesto(nombre, cfg) is None:
        hoy = date.today().year
        hojas = pd.ExcelFile(archivo, engine=N.MOTOR_EXCEL).sheet_names
        preguntas.append(_p('anio', 'presupuesto', nombre, nombre,
                            f'El archivo «{nombre}» no dice de qué año es el presupuesto: ¿de qué año es?',
                            [[str(a), str(a)] for a in range(hoy - 1, hoy + 3)], hojas[:5]))
    if hasattr(archivo, 'seek'):
        archivo.seek(0)
    conocidas = {**N.hotel_ids(cfg), **(cfg.get('alias_hoja') or {})}
    for hoja in pd.ExcelFile(archivo, engine=N.MOTOR_EXCEL).sheet_names:
        if hoja not in conocidas:
            preguntas.append(_p('hoja', 'presupuesto', nombre, hoja,
                                f'Hoja «{hoja}» del presupuesto: ¿de qué hotel es?',
                                _opciones_hoteles(cfg) + [[N.IGNORAR, 'No usar esta hoja']]))
    return preguntas


def _reservas(nombre, archivo, cfg):
    mapa = dict(zip(cfg['columnas_reservas']['Columna de Mews'], cfg['columnas_reservas']['Campo']))
    alias = N.alias_columnas(cfg, 'reservas')
    mapa.update(alias)
    df = pd.read_excel(archivo, engine=N.MOTOR_EXCEL)
    df = df.drop(columns=[c for c, d in mapa.items() if d == N.IGNORAR and c in df.columns])
    df = df.rename(columns={c: d for c, d in mapa.items() if d != N.IGNORAR})
    preguntas = _faltan('reservas', nombre, df, N.CAMPOS_RESERVA_OBLIGATORIOS, set(mapa.values()))
    if 'Hotel' in df.columns:
        ids = N.hotel_ids(cfg)
        for h in sorted({_texto(x) for x in df['Hotel'].dropna()} - set(ids)):
            preguntas.append(_p('hotel', 'reservas', nombre, h, f'Hotel «{h}» en las reservas: ¿a cuál corresponde?',
                                _opciones_hoteles(cfg)))
    if 'Origen' in df.columns:
        txt = lambda col: df[col].fillna('').astype(str).str.strip() if col in df.columns else pd.Series('', index=df.index)
        claves = {N._canal_clave(o, d, a) for o, d, a in zip(txt('Origen'), txt('Detalle origen'), txt('Agencia'))}
        canales = cfg['canales'].drop_duplicates('Canal')
        opciones = [[c, f'{c} ({t})'] for c, t in zip(canales['Canal'], canales['Tipo de canal'])]
        for k in sorted(claves - set(cfg['canales']['Valor en Mews']) - {''}):
            preguntas.append(_p('canal', 'reservas', nombre, k, f'Canal de reserva «{k}»: ¿cuál es?', opciones))
    return preguntas


DETECTORES = {'operador': _operador, 'business_central': _business_central, 'presupuesto': _presupuesto,
              'reservas': _reservas}


def detectar(tipo, nombre, archivo, cfg):
    """Preguntas sobre un archivo. Un archivo que ni siquiera se puede leer no genera preguntas: lo dirá la normalización."""
    try:
        return DETECTORES[tipo](nombre, archivo, cfg)
    except (ValueError, KeyError):
        return []


def aplicar_mapeos(cfg, mapeos):
    """Añade a la configuración lo confirmado en la web. mapeos: iterable de (tipo, clase, origen, destino)."""
    cfg = dict(cfg)
    alias_col, alias_hotel, alias_finca, alias_hoja, anios = {}, {}, {}, {}, {}
    cuentas, canales = [], []
    est = cfg['estructura_informe'].drop_duplicates('Línea').set_index('Línea')['Bloque']
    tipos_canal = cfg['canales'].drop_duplicates('Canal').set_index('Canal')['Tipo de canal']
    for tipo, clase, origen, destino in mapeos:
        if clase == 'columna':
            alias_col.setdefault(tipo, {})[origen] = destino
        elif clase == 'hotel':
            alias_hotel[origen] = destino
        elif clase == 'finca':
            alias_finca[origen] = destino
        elif clase == 'hoja':
            alias_hoja[origen] = destino
        elif clase == 'anio':
            anios[origen] = int(destino)
        elif clase == 'cuenta' and destino in est.index:
            cuentas.append({'Cuenta contable': int(origen) if re.fullmatch(r'\d+', origen) else origen,
                            'Ceco': '(cualquiera)', 'Descripción cuenta': 'Confirmada en la web',
                            'Línea del informe': destino, 'Bloque': est[destino]})
        elif clase == 'canal' and destino in tipos_canal.index:
            canales.append({'Valor en Mews': origen, 'Canal': destino, 'Tipo de canal': tipos_canal[destino],
                            'Descripción': 'Confirmado en la web'})
    cfg.update(alias_columnas=alias_col, alias_hotel=alias_hotel, alias_finca=alias_finca, alias_hoja=alias_hoja,
               anio_archivo=anios)
    if cuentas:
        cfg['plan_cuentas'] = pd.concat([cfg['plan_cuentas'], pd.DataFrame(cuentas)], ignore_index=True)
    if canales:
        cfg['canales'] = pd.concat([cfg['canales'], pd.DataFrame(canales)], ignore_index=True)
    return cfg
