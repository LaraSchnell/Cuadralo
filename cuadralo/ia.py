"""Cuádralo · Azure OpenAI (zona UE). La IA propone, el código calcula, una persona aprueba.

Variables de entorno (en Azure: App Service → Configuración → Variables de entorno):
  AZURE_OPENAI_ENDPOINT     p. ej. https://cuadralo-ia.openai.azure.com
  AZURE_OPENAI_API_KEY      clave del recurso (mejor desde Key Vault)
  AZURE_OPENAI_DEPLOYMENT   nombre de la implementación del modelo, p. ej. gpt-4o-mini
  AZURE_OPENAI_API_VERSION  opcional (por defecto 2024-10-21)
Sin ellas, Cuádralo funciona igual con sugerencias por parecido de nombres.
"""
import hashlib
import json
import logging
import os
import re
import urllib.request

log = logging.getLogger(__name__)

INSTRUCCIONES = (
    'Eres el asistente de alta de datos de Cuádralo, un control de gestión para hoteles. Para cada pregunta '
    'eliges UNA de sus opciones (el campo "valor" exacto) o null si no lo sabes. Nunca inventas opciones. '
    'Respondes solo JSON: {"respuestas": [{"id": <número>, "valor": <texto o null>, "confianza": <0 a 1>, '
    '"motivo": <frase corta en español>}]}'
)


def configurada():
    return all(os.environ.get(k) for k in ('AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_DEPLOYMENT'))


def _es_numero(t):
    return bool(re.fullmatch(r'[-+]?[\d.,\s%€$]+', str(t).strip()))


def _minimo(preguntas):
    """Lo único que sale hacia la IA: textos de la pregunta, opciones y ejemplos que no son cifras."""
    return [{'id': i, 'pregunta': p['texto'], 'que_es': p['clase'], 'origen': p['tipo'],
             'ejemplos': [m for m in p.get('muestras', []) if not _es_numero(m)][:3],
             'opciones': [{'valor': v, 'texto': e} for v, e in p['opciones']]}
            for i, p in enumerate(preguntas)]


def proponer(preguntas, registrar=None, abrir=urllib.request.urlopen):
    """{índice: {'valor', 'confianza', 'motivo'}}. Si algo falla devuelve {} y se quedan las sugerencias por parecido."""
    endpoint = os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')
    despliegue = os.environ['AZURE_OPENAI_DEPLOYMENT']
    version = os.environ.get('AZURE_OPENAI_API_VERSION', '2024-10-21')
    entrada = json.dumps(_minimo(preguntas), ensure_ascii=False)
    cuerpo = {'messages': [{'role': 'system', 'content': INSTRUCCIONES}, {'role': 'user', 'content': entrada}],
              'temperature': 0, 'response_format': {'type': 'json_object'}}
    url = f'{endpoint}/openai/deployments/{despliegue}/chat/completions?api-version={version}'
    ok, salida = False, {}
    try:
        req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method='POST', headers={
            'Content-Type': 'application/json', 'api-key': os.environ['AZURE_OPENAI_API_KEY']})
        with abrir(req, timeout=30) as r:
            datos = json.loads(r.read().decode())
        texto = datos['choices'][0]['message']['content']
        for r in json.loads(texto).get('respuestas', []):
            if r.get('valor') is None:
                continue
            conf = float(r.get('confianza') or 0)
            salida[int(r['id'])] = {'valor': str(r['valor']), 'confianza': round(min(max(conf, 0), 1), 2),
                                    'motivo': str(r.get('motivo') or '')}
        ok = True
    except Exception:
        log.exception('Azure OpenAI no respondió bien: se usan las sugerencias por parecido')
    if registrar:
        registrar(tarea='proponer_mapeo', modelo=despliegue, servidor=endpoint.split('//')[-1],
                  huella_entrada=hashlib.sha256(entrada.encode()).hexdigest(), n_preguntas=len(preguntas), ok=ok)
    return salida
