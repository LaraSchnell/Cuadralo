"""Formato español de cifras para las plantillas: 1.234.567 € y 46,1 %."""
from django import template

register = template.Library()


def _es(numero, decimales):
    texto = f'{numero:,.{decimales}f}'
    return texto.replace(',', '§').replace('.', ',').replace('§', '.')


@register.filter
def euros(valor, decimales=0):
    if valor is None:
        return '—'
    return f'{_es(float(valor), int(decimales))} €'


@register.filter
def pct(valor, decimales=1):
    if valor is None or valor != valor:
        return '—'
    return f'{_es(float(valor) * 100, int(decimales))} %'
