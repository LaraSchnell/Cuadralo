"""Paso 8: Revisar y confirmar. Lo desconocido se propone (parecido de nombres o IA) y una persona lo confirma."""
import io
import json

import openpyxl

from cuadralo import ia
from cuadralo.sugerencias import por_parecido
from portal.models import Carga, Empresa, FilaOperador, FilaPresupuesto, MapeoAprobado, MovimientoContable, Propuesta

from test_paso2_web import OCTUBRE, RAIZ, _entrar, demo  # noqa: F401  (fixture)

OPERADOR_OCT, BC_OCT = OCTUBRE[0][1], OCTUBRE[1][1]


def _subir(client, tipo, ruta):
    with open(ruta, 'rb') as f:
        return client.post('/subir/', {'tipo': tipo, 'archivos': [f]}, follow=True).content.decode()


def _confirmar_sugerencias(client, cambios=None):
    datos = {f'p_{p.id}': p.sugerencia for p in Propuesta.objects.filter(estado='pendiente')}
    datos.update(cambios or {})
    return client.post('/revisar/', datos, follow=True).content.decode()


def _operador_cambiado(tmp_path):
    wb = openpyxl.load_workbook(OPERADOR_OCT)
    ws = wb.active
    fila = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == 'Hotel')
    for c in range(1, ws.max_column + 1):
        if ws.cell(fila, c).value == 'Room Night vendidas':
            ws.cell(fila, c, value='Room nights vendidas (total)')
    for r in range(fila + 1, ws.max_row + 1):
        if ws.cell(r, 1).value == 'Hotel Mar':
            ws.cell(r, 1, value='Mar Hotel & Spa')
    ruta = tmp_path / 'Operador_octubre_nuevo_formato.xlsx'
    wb.save(ruta)
    return ruta


def test_operador_con_columna_y_hotel_renombrados_se_propone_y_se_confirma(client, demo, tmp_path):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    grupo = Empresa.objects.get(slug='grupo-demo')
    html = _subir(client, 'operador', _operador_cambiado(tmp_path))
    carga = Carga.objects.get(empresa=grupo, nombre_original='Operador_octubre_nuevo_formato.xlsx')
    assert carga.estado == 'revisar' and 'Revisar y confirmar' in html
    props = {p.clase: p for p in Propuesta.objects.filter(carga=carga)}
    assert props['hotel'].clave == 'Mar Hotel & Spa' and props['hotel'].sugerencia == 'MAR'
    assert props['columna'].sugerencia == 'Room Night vendidas' and props['columna'].fuente == 'parecido'
    pagina = client.get('/revisar/').content.decode()
    assert 'Mar Hotel &amp; Spa' in pagina and 'Propuesto por parecido de nombres' in pagina
    _confirmar_sugerencias(client)
    carga.refresh_from_db()
    assert carga.estado == 'ok', carga.mensaje
    assert MapeoAprobado.objects.filter(empresa=grupo, clase='hotel', origen='Mar Hotel & Spa', destino='MAR',
                                        aprobado_por__username='contable.demo').exists()
    assert FilaOperador.objects.filter(empresa=grupo, hotel='MAR', mes__year=2026, mes__month=10).exists()
    # La segunda vez ya no se pregunta
    wb = openpyxl.load_workbook(tmp_path / 'Operador_octubre_nuevo_formato.xlsx')
    wb.active.cell(1, 1, value=wb.active.cell(1, 1).value + ' ')   # otra huella, mismo formato
    otra = tmp_path / 'Operador_octubre_nuevo_formato_2.xlsx'
    wb.save(otra)
    _subir(client, 'operador', otra)
    assert Carga.objects.get(nombre_original=otra.name).estado == 'ok'


def test_bc_con_columna_renombrada_finca_y_cuenta_nuevas(client, demo, tmp_path):  # noqa: F811
    wb = openpyxl.load_workbook(BC_OCT)
    ws = wb.active
    cab = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
    ws.cell(1, cab['Importe'], value='Importe (EUR)')
    ws.cell(2, cab['Cód. dimensión 1 (FINCA)'], value='MAR-01')
    ws.cell(3, cab['Nº cuenta'], value=62900099)
    ws.cell(3, cab['Nombre cuenta'], value='Otros servicios exteriores')
    ruta = tmp_path / 'BC_octubre_otro_formato.xlsx'
    wb.save(ruta)
    _entrar(client, 'contable.demo', 'clave-contable-123')
    grupo = Empresa.objects.get(slug='grupo-demo')
    antes = MovimientoContable.objects.filter(empresa=grupo).count()
    _subir(client, 'business_central', ruta)
    props = {p.clase: p for p in Propuesta.objects.filter(estado='pendiente')}
    assert props['columna'].clave == 'Importe' and props['columna'].modo == 'falta'
    assert props['columna'].sugerencia == 'Importe (EUR)'
    assert props['finca'].clave == 'MAR-01' and props['cuenta'].clave == '62900099'
    assert 'Otros servicios exteriores' in props['cuenta'].muestras
    # Respuesta incompleta: no se guarda nada
    html = client.post('/revisar/', {}, follow=True).content.decode()
    assert 'Falta elegir una opción' in html and not MapeoAprobado.objects.exists()
    _confirmar_sugerencias(client, {f'p_{props["finca"].id}': 'MAR', f'p_{props["cuenta"].id}': 'Otros gastos generales'
                                    if 'Otros gastos generales' in dict(props['cuenta'].opciones) else
                                    props['cuenta'].opciones[0][0]})
    carga = Carga.objects.get(nombre_original=ruta.name)
    assert carga.estado == 'ok', carga.mensaje
    assert MovimientoContable.objects.filter(empresa=grupo).count() > antes
    assert not MovimientoContable.objects.filter(empresa=grupo, finca='MAR-01').exists()   # guardada como F001


def test_presupuesto_sin_año_y_con_hoja_que_sobra(client, demo, tmp_path):  # noqa: F811
    wb = openpyxl.load_workbook(RAIZ / 'datos_origen/presupuesto/Presupuesto_2026.xlsx')
    wb.create_sheet('Notas').cell(1, 1, value='Hipótesis del presupuesto')
    ruta = tmp_path / 'Presupuesto_definitivo.xlsx'
    wb.save(ruta)
    _entrar(client, 'contable.demo', 'clave-contable-123')
    grupo = Empresa.objects.get(slug='grupo-demo')
    _subir(client, 'presupuesto', ruta)
    props = {p.clase: p for p in Propuesta.objects.filter(estado='pendiente')}
    assert set(props) == {'anio', 'hoja'} and props['hoja'].clave == 'Notas'
    _confirmar_sugerencias(client, {f'p_{props["anio"].id}': '2026', f'p_{props["hoja"].id}': '(ignorar)'})
    assert Carga.objects.get(nombre_original=ruta.name).estado == 'ok'
    assert FilaPresupuesto.objects.filter(empresa=grupo, mes__year=2026).exists()


def test_solo_contabilidad_confirma_y_nadie_ve_lo_de_otra_empresa(client, demo, tmp_path):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir(client, 'operador', _operador_cambiado(tmp_path))
    p = Propuesta.objects.get(clase='hotel')
    _entrar(client, 'director.demo', 'clave-director-123')
    assert client.get('/revisar/').status_code == 403
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    pagina = client.get('/revisar/').content.decode()
    assert 'Mar Hotel' not in pagina and 'No hay nada pendiente' in pagina
    client.post('/revisar/', {f'p_{p.id}': 'MAR'})
    p.refresh_from_db()
    assert p.estado == 'pendiente' and not MapeoAprobado.objects.exists()


def test_parecido_de_nombres():
    p = {'clave': 'Hostal Mar', 'muestras': [], 'opciones': [['MAR', 'MAR · Hotel Mar'], ['BORN', 'BORN · Hotel Born']]}
    assert por_parecido(p)[0] == 'MAR'
    p = {'clave': 'XYZ', 'muestras': [], 'opciones': [['MAR', 'MAR · Hotel Mar']]}
    assert por_parecido(p) == (None, None)


def test_ia_solo_recibe_lo_minimo_y_solo_vale_una_opcion_valida(monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://prueba.openai.azure.com')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'x')
    monkeypatch.setenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o-mini')
    preguntas = [
        {'clase': 'cuenta', 'tipo': 'business_central', 'clave': '62900099', 'texto': 'Cuenta 62900099: ¿línea?',
         'muestras': ['Otros servicios', '1.234,56'], 'opciones': [['Suministros', 'Suministros'], ['Seguros', 'Seguros']]},
        {'clase': 'hotel', 'tipo': 'operador', 'clave': 'H1', 'texto': '¿Hotel?', 'muestras': [],
         'opciones': [['MAR', 'MAR · Hotel Mar']]},
    ]
    enviado = {}

    class Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def abrir(req, timeout):
        enviado['cuerpo'] = json.loads(req.data)
        contenido = json.dumps({'respuestas': [{'id': 0, 'valor': 'Suministros', 'confianza': 0.8, 'motivo': 'servicios'},
                                               {'id': 1, 'valor': 'INVENTADO', 'confianza': 0.9, 'motivo': ''}]})
        return Respuesta(json.dumps({'choices': [{'message': {'content': contenido}}]}).encode())

    registros = []
    r = ia.proponer(preguntas, registrar=lambda **kw: registros.append(kw), abrir=abrir)
    texto_enviado = enviado['cuerpo']['messages'][1]['content']
    assert '1.234,56' not in texto_enviado and 'Otros servicios' in texto_enviado   # las cifras no salen
    assert r[0]['valor'] == 'Suministros'
    assert registros[0]['ok'] and registros[0]['modelo'] == 'gpt-4o-mini' and len(registros[0]['huella_entrada']) == 64
    # sugerir() descarta lo que no es una opción válida
    from cuadralo import sugerencias
    monkeypatch.setattr(ia, 'proponer', lambda ps, registrar=None: r)
    sugerencias.sugerir(preguntas)
    assert preguntas[0]['fuente'] == 'ia' and preguntas[1]['sugerencia'] != 'INVENTADO'
