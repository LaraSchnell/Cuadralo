"""Configuración de la web de Cuádralo.

Todo lo que cambia entre el ordenador y Azure llega por variables de entorno (nunca claves en el código):
- En local, sin variables: SQLite y archivos en la carpeta media/.
- En Azure: Azure SQL (AZURE_SQL_*), Blob Storage (AZURE_STORAGE_*), claves desde Key Vault como variables de la aplicación.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or ('solo-para-desarrollo-local' if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError('Falta la variable DJANGO_SECRET_KEY')

ALLOWED_HOSTS = [h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',') if h]
if os.environ.get('WEBSITE_HOSTNAME'):  # Azure App Service lo define solo
    ALLOWED_HOSTS.append(os.environ['WEBSITE_HOSTNAME'])
CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in ALLOWED_HOSTS if h not in ('localhost', '127.0.0.1', 'testserver')]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'portal',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'web.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'web.wsgi.application'

# Base de datos: Azure SQL si hay variables; si no, SQLite en local.
if os.environ.get('AZURE_SQL_SERVER'):
    DATABASES = {'default': {
        'ENGINE': 'mssql',
        'NAME': os.environ['AZURE_SQL_DATABASE'],
        'USER': os.environ['AZURE_SQL_USER'],
        'PASSWORD': os.environ['AZURE_SQL_PASSWORD'],
        'HOST': os.environ['AZURE_SQL_SERVER'],
        'PORT': '1433',
        'OPTIONS': {'driver': 'ODBC Driver 18 for SQL Server', 'extra_params': 'Encrypt=yes;TrustServerCertificate=no'},
    }}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

# Archivos subidos: Blob Storage en Azure, carpeta media/ en local.
if os.environ.get('AZURE_STORAGE_ACCOUNT_NAME'):
    STORAGES = {
        'default': {'BACKEND': 'storages.backends.azure_storage.AzureStorage', 'OPTIONS': {
            'account_name': os.environ['AZURE_STORAGE_ACCOUNT_NAME'],
            'account_key': os.environ['AZURE_STORAGE_ACCOUNT_KEY'],
            'azure_container': os.environ.get('AZURE_STORAGE_CONTAINER', 'cargas'),
            'overwrite_files': False,
        }},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }
else:
    MEDIA_ROOT = BASE_DIR / 'media'
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'inicio'
LOGOUT_REDIRECT_URL = 'login'
DATA_UPLOAD_MAX_NUMBER_FILES = 100

# Seguridad en Azure (HTTPS lo pone App Service).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_AGE = 8 * 3600

# Configuración del cliente demo (en el repositorio, solo datos ficticios).
CONFIG_DEMO = BASE_DIR / 'configuracion_grupo_demo.xlsx'
DATOS_DEMO = BASE_DIR / 'datos_origen'

LOGGING = {
    'version': 1,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
