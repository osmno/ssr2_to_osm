import logging
logger = logging.getLogger('utility_to_osm.ssr2.OSMstedsnr')

from utility_to_osm.osmapis import osmapis
#from osmapis import *

class OSMstedsnr(osmapis.OSM):
    """Adds the container stedsnr to osmpais.OSM, 
    where the dictionary key is the ssr:stedsnr value
    and the value is a list (hopefully length 1) with a 
    osmapis.Node/osmapis.Way/osmapis.Relation object.
    Example usage
    o = OSMstedsnr.from_xml(xml)
    o.stedsnr['3234487807']
    In addition, a list of any duplicate elements is stored in:
    o.stedsnr_duplicates
    """
    
    def __init__(self, *args, **kwargs):
        self.stedsnr = {}
        self.stedsnr_duplicates = set()
        super(OSMstedsnr, self).__init__(*args, **kwargs)
    
    def add(self, item):
        if 'ssr:stedsnr' in item.tags:
            key = item.tags['ssr:stedsnr']
            if key in self.stedsnr:
                self.stedsnr_duplicates.add(self.stedsnr[key][0])
                self.stedsnr_duplicates.add(item)
                                
                logger.error('Multiple objects with ssr:stedsnr found please fix this, %s, %s', item, self.stedsnr[key])
                self.stedsnr[key].append(item)
            else:
                self.stedsnr[key] = [item]

        return super(OSMstedsnr, self).add(item)

    def discard(self, item):
        if 'ssr:stedsnr' in item.tags:
            key = item.tags['ssr:stedsnr']
            self.stedsnr.pop(key, None)
            
        return super(OSMstedsnr, self).discard(item)

osmapis.wrappers["osm"] = OSMstedsnr
