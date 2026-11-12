"""Genera los Excels ficticios de reservas del Grupo Demo (un archivo por mes de llegada).

Imitan lo que da Mews por su API (Get all reservations) o por el export del informe de reservas:
número, estado, origen, detalle del origen, agencia (OTA), segmento, tarifa, tipo de habitación,
fechas, número de adultos y niños, nacionalidad e ingresos de alojamiento sin IVA.
No llevan nombres ni datos de contacto de los huéspedes: no hacen falta para el control de gestión.

Las reservas cuadran con el informe del operador de cada hotel y mes: las noches suman sus room nights
y los ingresos suman su total de alojamiento. Simplificación de los datos ficticios: ninguna estancia
cruza de un mes a otro (el código de Cuádralo sí reparte las noches entre meses si cruzan).

Uso: python herramientas/generar_reservas.py
"""
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from cuadralo.normalizar import normalizar_operador  # noqa: E402

SEMILLA = 2026

# canal: (origen Mews, detalle del origen, agencia, peso, factor de precio, antelación media en días, % cancelación)
CANALES = [
    ('ChannelManager', '', 'Booking.com', 0.36, 1.00, 32, 0.22),
    ('ChannelManager', '', 'Expedia', 0.13, 1.02, 38, 0.18),
    ('ChannelManager', '', 'Hotelbeds', 0.09, 0.82, 55, 0.10),
    ('Distributor', '', '', 0.17, 0.95, 28, 0.08),
    ('Commander', 'Phone', '', 0.06, 0.97, 14, 0.05),
    ('Commander', 'Email', '', 0.07, 0.92, 21, 0.06),
    ('Commander', 'InPerson', '', 0.03, 1.05, 0, 0.00),
    ('ChannelManager', '', 'Viajes El Corte Inglés', 0.04, 0.88, 45, 0.08),
    ('Commander', 'Email', 'Agencia Grupos BCN', 0.012, 0.78, 70, 0.12),
]
SEGMENTO = {'Booking.com': 'Ocio', 'Expedia': 'Ocio', 'Hotelbeds': 'Turoperador', 'Viajes El Corte Inglés': 'Ocio',
            'Agencia Grupos BCN': 'Grupos'}
TARIFAS = {'Ocio': ['Flexible', 'No reembolsable', 'Con desayuno'], 'Empresa': ['Tarifa empresa'],
           'Turoperador': ['Tarifa neta turoperador'], 'Grupos': ['Tarifa grupo']}
CATEGORIAS = [('Doble', 0.55, 1.0), ('Doble superior', 0.25, 1.2), ('Individual', 0.12, 0.8), ('Suite', 0.08, 1.8)]
PAISES = [('ES', 0.30), ('FR', 0.12), ('GB', 0.12), ('US', 0.10), ('DE', 0.09), ('IT', 0.08), ('NL', 0.05),
          ('CH', 0.03), ('MX', 0.03), ('AR', 0.02), ('OT', 0.06)]
COLUMNAS = ['Service', 'Number', 'State', 'Origin', 'CommanderOrigin', 'TravelAgency', 'BusinessSegment', 'Rate',
            'RequestedCategory', 'CreatedUtc', 'CanceledUtc', 'ScheduledStartUtc', 'ScheduledEndUtc',
            'AdultCount', 'ChildCount', 'Nationality', 'Purpose', 'AccommodationRevenue']


def operador():
    cfg = pd.read_excel(os.path.join(RAIZ, 'configuracion_grupo_demo.xlsx'), sheet_name=None)
    pms = normalizar_operador(sorted(glob.glob(os.path.join(RAIZ, 'datos_origen/operador/*.xlsx'))), cfg)
    t = pms.pivot_table(index=['Id hotel', 'Fecha'], columns='Concepto', values='Valor', aggfunc='sum')
    nombres = cfg['hoteles'].set_index('Id hotel')['Hotel']
    return t[['Room nights', 'Alojamiento', 'Pax x room']].reset_index(), nombres


def reservas_mes(rng, hotel, nombre, mes, rn_objetivo, ingresos, pax, numero):
    dias = mes.days_in_month
    pesos = np.array([c[3] for c in CANALES])
    filas, noches_total = [], 0
    while noches_total < rn_objetivo:
        c = CANALES[rng.choice(len(CANALES), p=pesos / pesos.sum())]
        origen, detalle, agencia, _, factor, antel, p_cancel = c
        grupo = agencia == 'Agencia Grupos BCN'
        noches = int(min(rng.choice([1, 2, 2, 3, 3, 4, 5, 7]), rn_objetivo - noches_total))
        habitaciones = int(rng.integers(4, 9)) if grupo else 1
        habitaciones = max(1, min(habitaciones, (rn_objetivo - noches_total) // max(noches, 1)))
        llegada = int(rng.integers(1, dias - noches + 2))
        segmento = SEGMENTO.get(agencia) or ('Empresa' if origen == 'Commander' and rng.random() < 0.6 else 'Ocio')
        tarifa = rng.choice(TARIFAS[segmento])
        cat = CATEGORIAS[rng.choice(len(CATEGORIAS), p=[x[1] for x in CATEGORIAS])]
        pais = PAISES[rng.choice(len(PAISES), p=[x[1] for x in PAISES])][0]
        inicio = mes + pd.Timedelta(days=llegada - 1, hours=14)
        creada = inicio - pd.Timedelta(days=int(rng.exponential(antel)) if antel else 0, hours=int(rng.integers(1, 12)))
        for _ in range(habitaciones):
            adultos = 1 if cat[0] == 'Individual' else int(rng.choice([1, 2, 2, 2, 3], p=[0.15, 0.3, 0.3, 0.15, 0.1]))
            ninos = 0 if segmento in ('Empresa', 'Grupos') else int(rng.choice([0, 0, 0, 1, 2]))
            filas.append({'Service': nombre, 'Number': str(numero), 'State': 'Processed', 'Origin': origen,
                          'CommanderOrigin': detalle, 'TravelAgency': agencia, 'BusinessSegment': segmento,
                          'Rate': tarifa, 'RequestedCategory': cat[0], 'CreatedUtc': creada, 'CanceledUtc': pd.NaT,
                          'ScheduledStartUtc': inicio, 'ScheduledEndUtc': inicio + pd.Timedelta(days=noches, hours=-3),
                          'AdultCount': adultos, 'ChildCount': ninos, 'Nationality': pais,
                          'Purpose': 'Business' if segmento == 'Empresa' else 'Leisure',
                          '_noches': noches, '_peso': noches * factor * cat[2]})
            numero += 1
            noches_total += noches
        # cancelaciones: reservas que no llegan a la estancia (no suman noches ni ingresos)
        if rng.random() < p_cancel:
            cancelada = dict(filas[-1])
            cancelada.update({'Number': str(numero), 'State': 'Canceled', 'CanceledUtc': creada + (inicio - creada) * rng.random(),
                              '_noches': 0, '_peso': 0})
            filas.append(cancelada)
            numero += 1
    df = pd.DataFrame(filas)
    # ingresos: se reparten según noches × precio relativo y se ajustan al céntimo al total del operador
    validas = df['_peso'] > 0
    importes = (df.loc[validas, '_peso'] / df.loc[validas, '_peso'].sum() * ingresos).round(2)
    importes.iloc[-1] += round(ingresos - importes.sum(), 2)
    df['AccommodationRevenue'] = 0.0
    df.loc[validas, 'AccommodationRevenue'] = importes.round(2)
    return df, numero


def main():
    rng = np.random.default_rng(SEMILLA)
    op, nombres = operador()
    carpeta = os.path.join(RAIZ, 'datos_origen/reservas')
    for f in glob.glob(os.path.join(carpeta, '*.xlsx')):
        os.remove(f)
    numero = 100001
    for mes, filas_mes in op.groupby('Fecha'):
        partes = []
        for _, r in filas_mes.iterrows():
            df, numero = reservas_mes(rng, r['Id hotel'], nombres[r['Id hotel']], pd.Timestamp(mes),
                                      int(r['Room nights']), float(r['Alojamiento']), float(r['Pax x room']), numero)
            assert df['_noches'].sum() == int(r['Room nights'])
            assert abs(df['AccommodationRevenue'].sum() - float(r['Alojamiento'])) < 0.005
            partes.append(df)
        todo = pd.concat(partes, ignore_index=True).sort_values(['Service', 'ScheduledStartUtc'])
        for col in ('CreatedUtc', 'CanceledUtc', 'ScheduledStartUtc', 'ScheduledEndUtc'):
            todo[col] = pd.to_datetime(todo[col]).dt.floor('min')
        salida = os.path.join(carpeta, f'Reservas_{pd.Timestamp(mes):%Y-%m}.xlsx')
        todo[COLUMNAS].to_excel(salida, index=False, sheet_name='Reservations')
        print(salida, len(todo))


if __name__ == '__main__':
    main()
