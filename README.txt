python -m venv venv
venv\Scripts\activate
pip install 
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser(name: root/pass: root)
python manage.py runserver
pip install django djangorestframework django-allauth psycopg2-binary gunicorn celery redis django-crispy-forms
django-admin startproject bible_academy
python manage.py startapp accounts
python manage.py startapp courses
python manage.py startapp enrollments
python manage.py startapp meetings