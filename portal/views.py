import pandas as pd
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cuadralo import informe
from .acceso import perfil_requerido
from .models import Carga, InteresModulo, Perfil
from .procesar import datos_empresa, leer_configuracion, presupuesto_empresa, procesar_empresa, registrar_carga

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']


def _mes_texto(ts):
    return f'{MESES[ts.month - 1]} {ts.year}'


@perfil_requerido
def inicio(request):
    empresa, perfil = request.empresa, request.perfil
    mov, pms = datos_empresa(empresa)
    contexto = {'empresa': empresa, 'perfil': perfil, 'informe': None, 'meses': []}
    if len(mov) == 0 or len(pms) == 0:
        return render(request, 'portal/inicio.html', contexto)

    cfg = leer_configuracion(empresa)
    datos = informe.Datos(mov, pms, presupuesto_empresa(empresa), cfg)
    if not datos.meses:
        return render(request, 'portal/inicio.html', contexto)

    # Hoteles que puede ver este usuario: el director de hotel, solo el suyo (nunca se toma de la URL)
    visibles = list(cfg['hoteles']['Id hotel'])
    if perfil.rol == Perfil.DIRECTOR_HOTEL:
        visibles = [perfil.hotel]
    opciones_hotel = ([('GRUPO', 'Todo el grupo')] if len(visibles) > 1 else []) + [(h, datos.nombres[h]) for h in visibles]
    seleccion = request.GET.get('hotel')
    if seleccion not in dict(opciones_hotel):
        seleccion = opciones_hotel[0][0]

    pedido = request.GET.get('mes')
    try:
        mes = pd.Timestamp(pedido + '-01') if pedido else None
    except ValueError:
        mes = None
    if mes not in datos.meses:
        mes = datos.meses[0]
    modo = 'acumulado' if request.GET.get('periodo') == 'acumulado' else 'mes'

    contenido = informe.construir(datos, visibles, seleccion, mes, modo)
    ultima = Carga.objects.filter(empresa=empresa, estado='ok').order_by('-creada').first()
    contexto.update({
        'informe': contenido, 'mes': mes, 'mes_texto': _mes_texto(mes), 'modo': modo,
        'meses': [(m.strftime('%Y-%m'), _mes_texto(m)) for m in datos.meses],
        'opciones_hotel': opciones_hotel, 'seleccion': seleccion, 'ultima_carga': ultima,
        'intereses': set(InteresModulo.objects.filter(empresa=empresa, usuario=request.user).values_list('modulo', flat=True)),
        'pagina': request.GET.get('p', 'resumen'),
    })
    return render(request, 'portal/inicio.html', contexto)


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
