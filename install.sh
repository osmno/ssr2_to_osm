#!/bin/sh

pip install -r requirements.txt

(cd ..; git clone git@github.com:NKAmapper/ssr2osm.git)

# yeah, not very pythonic I know...
git clone https://github.com/obtitus/py_import_utility_to_osm
mv py_import_utility_to_osm/utility_to_osm utility_to_osm
cd utility_to_osm
git clone https://github.com/xificurk/osmapis
cp osmapis/osmapis.py .
