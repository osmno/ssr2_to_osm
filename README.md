# SSR2 import to OpenStreetMap.org
This project fetches and translates data from the Norwegian Mapping Authorities (Kartverket)
using the ssr2 api at wfs.geonorge.no. See:

https://wiki.openstreetmap.org/wiki/No:Import_av_stedsnavn_fra_SSR2

for details on the import.

## Installation
Use `install.sh`, requires `git` and `pip`.

## Usage
See `ssr2.py --help`. Note that calling `ssr2.py` without any arguments
will start downloading and processing every kommune in Norway, which takes a while...

## Output
The script output is currently here:

https://drive.google.com/open?id=1d_m4gsw6ygok5o2DahwauLpnkSeFhEov