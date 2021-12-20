# standard python imports
import re
import zipfile
import logging
logger = logging.getLogger('utility_to_osm.ssr2')

# third party imports
from bs4 import BeautifulSoup

# shared helper library
import utility_to_osm.gentle_requests as gentle_requests

def get_geonorge_url_dct(url='https://nedlasting.geonorge.no/geonorge/Basisdata/Stedsnavn/GML/'):
    geonorge = dict()

    req = gentle_requests.GentleRequests()
    data = req.get(url)
    #print(data.content)

    soup = BeautifulSoup(data.content, 'lxml-xml')
    #print(soup.prettify())
    for link in soup.find_all('a'):
        href = link.get('href')
        if href.startswith('Basisdata_0000_Norge'):
            continue
        
        reg = re.match('Basisdata_(\d\d\d\d)_(\w+)_25832_Stedsnavn_GML.zip', href)
        if reg:
            href = url + href
            kommunenummer, kommunenavn = reg.groups()
            kommunenavn = kommunenavn.replace('_', ' ')

            geonorge[kommunenummer] = href

    return geonorge

def download_unzip_geonorge(zip_url, zip_filename):
    req = gentle_requests.GentleRequests()
    
    data = req.get_cached(zip_url, zip_filename, file_mode='b')
    if data is None:
        return None

    # fixme: wrap data as a file-like object
    with zipfile.ZipFile(zip_filename, 'r') as z:
        namelist = z.namelist()
        assert len(namelist) == 1, 'expected single file in zip, got %s' % z.namelist
        
        for name in namelist:
            with z.open(name, 'r') as f:
                content = f.read()

    return content

if __name__ == '__main__':
    geonorge_urls = get_geonorge_url_dct()
    
    for key, item in geonorge_urls.items():
        print(key, item)

    # lets try it out
    c = download_unzip_geonorge(item, 'test.zip')
    soup = BeautifulSoup(c, 'lxml-xml')
    
    print(soup.prettify())
