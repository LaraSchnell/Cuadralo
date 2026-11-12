"""Formato español de cifras para las plantillas: 1.234.567 € y 46,1 %."""
from django import template

register = template.Library()


def _es(numero, decimales):
    texto = f'{numero:,.{decimales}f}'
    return texto.replace(',', '§').replace('.', ',').replace('§', '.')


@register.filter
def euros(valor, decimales=0):
    if valor is None or valor != valor:
        return '—'
    return f'{_es(float(valor), int(decimales))} €'


@register.filter
def pct(valor, decimales=1):
    if valor is None or valor != valor:
        return '—'
    return f'{_es(float(valor) * 100, int(decimales))} %'


@register.filter
def clave(diccionario, nombre):
    """Lee una columna con espacios o tildes: {{ fila|clave:'Año anterior' }}."""
    try:
        return diccionario.get(nombre)
    except AttributeError:
        return None


@register.filter
def safe_json(valor):
    """Un diccionario como JSON escapado para ponerlo dentro de un atributo HTML (data-clic='...')."""
    import json
    from django.utils.html import escape
    from django.utils.safestring import mark_safe
    return mark_safe(escape(json.dumps(valor, ensure_ascii=False)))
