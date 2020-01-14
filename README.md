# SSR2 import to OpenStreetMap.org
This project fetches and translates data from the Norwegian Mapping Authorities (Kartverket)
using the SSR2 API at wfs.geonorge.no. See:

https://wiki.openstreetmap.org/wiki/No:Import_av_stedsnavn_fra_SSR2

for details on the import.

## Installation
Use `install.sh`, requires `git` and `pip`.

## Usage
See `ssr2.py --help`. Note that calling `ssr2.py` without any arguments
downloads and processes every Norwegian municipality, which takes a while…

## Output
The script output is currently to be found here:
https://obtitus.github.io/ssr2_to_osm_data/
