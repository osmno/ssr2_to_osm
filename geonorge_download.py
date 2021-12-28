# standard python imports
import re
import time
import random
import zipfile
import logging
logger = logging.getLogger('utility_to_osm.ssr2')

# third party imports
from bs4 import BeautifulSoup

# shared helper library
import utility_to_osm.gentle_requests as gentle_requests

def get_geonorge_url_dct(url='https://nedlasting.geonorge.no/geonorge/Basisdata/Stedsnavn/GML/'):
    '''
    Returns a dictionary with kommunenummer (as 4 character string) as key and the geonorge zip url as value
    {kommunenummer: url}
    '''
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

        # ignore projection, for kommuner with both, the last one will be used
        reg = re.match('Basisdata_(\d\d\d\d)_([-\w]+)_\d+_Stedsnavn_GML.zip', href)
        if reg:
            href = url + href
            kommunenummer, kommunenavn = reg.groups()
            kommunenavn = kommunenavn.replace('_', ' ')

            geonorge[kommunenummer] = href

    return geonorge

def unzip(zip_filename):
    content = None
    with zipfile.ZipFile(zip_filename, 'r') as z:
        namelist = z.namelist()
        assert len(namelist) == 1, 'expected single file in zip, got %s' % z.namelist

        for name in namelist:
            with z.open(name, 'r') as f:
                content = f.read()

    return content

def download_unzip_geonorge(zip_url, zip_filename):
    req = gentle_requests.GentleRequests()
    
    data = req.get_cached(zip_url, zip_filename, file_mode='b')
    if data is None:
        return None

    # fixme: wrap data as a file-like object
    try:
        content = unzip(zip_filename)
    except zipfile.BadZipFile as e:
        # lets try again
        logger.error('Bad zip file, trying again %s', e)
        time.sleep(random.randrange(0, 15))
        data = req.get_cached(zip_url, zip_filename, file_mode='b', old_age_days=0)
        content = unzip(zip_filename)
                    
    return content

def legacy_download_geonorge(kommunenummer, xml_filename, url=None):
    if url is None:
        url = 'http://wfs.geonorge.no/skwms1/wfs.stedsnavn50?VERSION=2.0.0&SERVICE=WFS&srsName=EPSG:25832&REQUEST=GetFeature&TYPENAME=Sted&resultType=results&Filter=%3CFilter%3E%20%3CPropertyIsEqualTo%3E%20%3CValueReference%20xmlns:app=%22http://skjema.geonorge.no/SOSI/produktspesifikasjon/Stedsnavn/5.0%22%3Eapp:kommune/app:Kommune/app:kommunenummer%3C/ValueReference%3E%20%3CLiteral%3E{kommunenummer}%3C/Literal%3E%20%3C/PropertyIsEqualTo%3E%20%3C/Filter%3E" --header "Content-Type:text/xml"'
        url = url.format(kommunenummer=kommunenummer)
    
    # get xml:
    req = gentle_requests.GentleRequests()
    d = req.get_cached(url, xml_filename)
    try: d = d.decode('utf-8')
    except:pass
    
    ensure_contains = '</wfs:FeatureCollection>'
    if ensure_contains not in d[-len(ensure_contains)-100:]:
        logger.error('ERROR, no ending in %s? Trying to re-download "%s"',
                     xml_filename, d[-len(ensure_contains)-100:-1])
        time.sleep(random.randrange(0, 15))
        d = req.get_cached(url, xml_filename, old_age_days=0.1)
        try: d = d.decode('utf-8')
        except:pass

    if ensure_contains not in d[-len(ensure_contains)-100:]:
        raise Exception("Still no file ending for %s" % (xml_filename))

    return d

if __name__ == '__main__':
    geonorge_urls = get_geonorge_url_dct()
    
    for key, item in geonorge_urls.items():
        print(key, item)

    # lets try it out
    c = download_unzip_geonorge(item, 'test.zip')
    soup = BeautifulSoup(c, 'lxml-xml')
    
    # print(soup.prettify())
