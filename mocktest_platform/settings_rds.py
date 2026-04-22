from .settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('RDS_DB_NAME', 'postgres'),
        'USER': os.getenv('RDS_DB_USER', 'postgres'),
        'PASSWORD': os.getenv('RDS_DB_PASSWORD', ''),
        'HOST': os.getenv('RDS_DB_HOST', ''),
        'PORT': os.getenv('RDS_DB_PORT', '5432'),
    }
}
