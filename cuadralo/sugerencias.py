"""Cuádralo · sugerencias para las preguntas de revisión.

1. Siempre: parecido de nombres (sin IA, sin salir de la web).
2. Si Azure OpenAI está configurado (zona UE): la IA propone y, si su respuesta es una de las opciones válidas,
   sustituye a la del parecido. La IA solo recibe cabeceras, nombres y textos cortos de ejemplo: nunca importes,
   NIF ni datos de huéspedes.

Siempre es una propuesta: la confirma una persona en la web.
"""
import difflib
import re
import unicodedata

UMBRAL = 0.45


def _limpio(t):
    t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', t).strip()


def parecido(a, b):
    """0-1: mezcla de parecido de letras y de palabras en común."""
    a, b = _limpio(a), _limpio(b)
    if not a or not b:
        return 0.0
    letras = difflib.SequenceMatcher(None, a, b).ratio()
    pa, pb = set(a.split()), set(b.split())
    palabras = len(pa & pb) / max(len(pa | pb), 1)
    contiene = 0.9 if (a in b or b in a) and min(len(a), len(b)) >= 3 else 0
    return max(letras, palabras, contiene)


def por_parecido(pregunta):
    """(valor, confianza) de la opción que más se parece, o (None, None)."""
    textos = [pregunta['clave']] + list(pregunta.get('muestras') or [])
    mejor, nota = None, 0.0
    for valor, etiqueta in pregunta['opciones']:
        n = max(parecido(t, x) for t in textos for x in (valor, etiqueta))
        if n > nota:
            mejor, nota = valor, n
    return (mejor, round(nota, 2)) if nota >= UMBRAL else (None, None)


def sugerir(preguntas, registrar_ia=None):
    """Rellena en cada pregunta: sugerencia, confianza (0-1), fuente ('ia' o 'parecido') y motivo."""
    from cuadralo import ia
    for p in preguntas:
        valor, conf = por_parecido(p)
        p.update(sugerencia=valor or '', confianza=conf, fuente='parecido' if valor else '',
                 motivo='Nombre parecido' if valor else '')
    if preguntas and ia.configurada():
        respuestas = ia.proponer(preguntas, registrar=registrar_ia)
        for i, p in enumerate(preguntas):
            r = respuestas.get(i)
            if r and r['valor'] in {v for v, _ in p['opciones']}:
                p.update(sugerencia=r['valor'], confianza=r['confianza'], fuente='ia', motivo=r['motivo'][:300])
    return preguntas
