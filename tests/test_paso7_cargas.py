"""Paso 7: cargas seguras. Archivos idénticos, meses repetidos, eliminar cargas, errores claros y registro de actividad."""
import openpyxl

from portal.models import Carga, Empresa, MovimientoContable, RegistroActividad

from test_paso2_web import OCTUBRE, _entrar, _subir_octubre, demo  # noqa: F401  (fixture)

BC_OCT = OCTUBRE[1][1]


def _subir(client, tipo, ruta):
    with open(ruta, 'rb') as f:
        return client.post('/subir/', {'tipo': tipo, 'archivos': [f]}, follow=True).content.decode()


def test_archivo_identico_con_otro_nombre_no_se_carga_dos_veces(client, demo, tmp_path):  # noqa: F811
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    prueba = Empresa.objects.get(slug='prueba-aislamiento')
    antes = MovimientoContable.objects.filter(empresa=prueba).count()
    copia = tmp_path / 'BC_octubre_otra_vez.xlsx'
    copia.write_bytes(BC_OCT.read_bytes())
    html = _subir(client, 'business_central', copia)
    assert 'no se ha subido: es idéntico a' in html
    assert MovimientoContable.objects.filter(empresa=prueba).count() == antes
    assert not Carga.objects.filter(empresa=prueba, nombre_original='BC_octubre_otra_vez.xlsx').exists()


def test_mismo_mes_en_dos_archivos_avisa_y_no_duplica(client, demo, tmp_path):  # noqa: F811
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    prueba = Empresa.objects.get(slug='prueba-aislamiento')
    antes = MovimientoContable.objects.filter(empresa=prueba).count()
    # Re-export de octubre con otro nombre y un cambio (distinta huella): mismos «Nº mov.»
    wb = openpyxl.load_workbook(BC_OCT)
    wb.active.cell(row=2, column=9, value='Descripción corregida')
    nuevo = tmp_path / 'BC_octubre_v2.xlsx'
    wb.save(nuevo)
    html = _subir(client, 'business_central', nuevo)
    assert 'Revisa si has cargado dos veces el mismo mes' in html and 'octubre 2026' in html
    assert MovimientoContable.objects.filter(empresa=prueba).count() == antes          # no se cuenta dos veces
    assert MovimientoContable.objects.filter(empresa=prueba, descripcion='Descripción corregida').count() == 1


def test_eliminar_una_carga_la_quita_del_informe(client, demo):  # noqa: F811
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    prueba = Empresa.objects.get(slug='prueba-aislamiento')
    bc = Carga.objects.get(empresa=prueba, tipo='business_central')
    html = client.post(f'/cargas/{bc.id}/eliminar/', follow=True).content.decode()
    assert 'eliminado' in html
    bc.refresh_from_db()
    assert bc.estado == 'eliminada' and bc.eliminada_por.username == 'usuario.prueba'
    assert MovimientoContable.objects.filter(empresa=prueba).count() == 0
    assert 'Todavía no hay datos' in client.get('/').content.decode()


def test_no_se_puede_eliminar_una_carga_de_otra_empresa_ni_siendo_director(client, demo):  # noqa: F811
    grupo = Empresa.objects.get(slug='grupo-demo')
    ajena = Carga.objects.filter(empresa=grupo, estado='ok').first()
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    assert client.post(f'/cargas/{ajena.id}/eliminar/').status_code == 404
    _entrar(client, 'director.demo', 'clave-director-123')
    assert client.post(f'/cargas/{ajena.id}/eliminar/').status_code == 403
    ajena.refresh_from_db()
    assert ajena.estado == 'ok'


def test_business_central_sin_columnas_avisa_cuales_faltan(client, demo, tmp_path):  # noqa: F811
    wb = openpyxl.load_workbook(BC_OCT)
    wb.active.delete_cols(10)   # «Importe»
    malo = tmp_path / 'BC_sin_importe.xlsx'
    wb.save(malo)
    _entrar(client, 'contable.demo', 'clave-contable-123')
    html = _subir(client, 'business_central', malo)
    assert 'le faltan las columnas' in html and 'Importe' in html


def test_tipo_equivocado_da_un_error_claro(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    html = _subir(client, 'operador', BC_OCT)   # un export de BC subido como informe del operador
    assert 'Error' in html and 'no encuentro' in html


def test_se_registra_que_ve_y_exporta_cada_usuario(client, demo):  # noqa: F811
    _entrar(client, 'director.demo', 'clave-director-123')
    client.get('/?meses=2026-09&p=resultados')
    client.get('/exportar/cuenta/?meses=2026-09')
    acciones = list(RegistroActividad.objects.filter(usuario__username='director.demo').values_list('accion', 'detalle'))
    assert ('inicio', '/?meses=2026-09&p=resultados') in acciones
    assert any(a == 'exportar' and 'cuenta' in d for a, d in acciones)


def test_mismo_mes_del_operador_en_dos_archivos_manda_el_mas_reciente(client, demo, tmp_path):  # noqa: F811
    from portal.models import FilaOperador
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    prueba = Empresa.objects.get(slug='prueba-aislamiento')
    antes = FilaOperador.objects.filter(empresa=prueba).count()
    wb = openpyxl.load_workbook(OCTUBRE[0][1])
    ws = wb.active
    fila = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == 'Hotel') + 1
    ws.cell(fila, 2, value=(ws.cell(fila, 2).value or 0) + 1)   # cambia una cifra: otra huella
    nuevo = tmp_path / 'Operador_octubre_corregido.xlsx'
    wb.save(nuevo)
    html = _subir(client, 'operador', nuevo)
    assert 'Revisa si has cargado dos veces el mismo mes' in html
    assert FilaOperador.objects.filter(empresa=prueba).count() == antes   # no se suma dos veces
