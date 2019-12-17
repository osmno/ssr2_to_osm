FROM ubuntu:17.10
#FROM python:2.7-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    apache2 \
    git \
    python-pip python-dev build-essential 
RUN pip install --upgrade pip

# # Install apache and write hello world message
# RUN echo "Hello World!" > /var/www/index.html

# # Configure apache
# RUN a2enmod rewrite
# RUN chown -R www-data:www-data /var/www
# ENV APACHE_RUN_USER www-data
# ENV APACHE_RUN_GROUP www-data
# ENV APACHE_LOG_DIR /var/log/apache2

EXPOSE 80

ADD https://api.github.com/repos/obtitus/ssr2_to_osm/git/refs/heads/master version.json
RUN git clone https://github.com/obtitus/ssr2_to_osm &&\
    (cd ssr2_to_osm;sh install.sh)
    #&&\
    #python ssr2_to_osm/ssr2.py --output output --kommune 2111

COPY . /ssr2_to_osm
WORKDIR /ssr2_to_osm

ENTRYPOINT ["python"]
CMD ["flask_app.py"]

# CMD ["source", "/etc/apache2/envvars", ";", "/usr/sbin/apache2", "-D",  "FOREGROUND"]
#CMD ["FLASK_APP=ssr2_to_osm/flask_app.py", "flask", "run"]