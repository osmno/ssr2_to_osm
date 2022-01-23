#/usr/bin/env python
import sys
import logging
logger = logging.getLogger('utility_to_osm.ssr2.git_diff')

import utility_to_osm.file_util as file_util
from osmapis_stedsnr import OSMstedsnr

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    # diff is called by git with 7 parameters:
    # path old-file old-hex old-mode new-file new-hex new-mode

    new_file, old_file = sys.argv[1], sys.argv[2]

    logger.info('Reading %s', old_file)
    content = file_util.read_file(old_file)
    old_osm = OSMstedsnr.from_xml(content)

    logger.info('Reading %s', new_file)    
    content = file_util.read_file(new_file)
    new_osm = OSMstedsnr.from_xml(content)
    
    print('\n=== Missing stedsnr ===\n')
    old_stedsnr = sorted(old_osm.stedsnr.keys())
    new_stedsnr = sorted(new_osm.stedsnr.keys())
    
    for key in old_stedsnr:
        if key not in new_stedsnr:
            print('Diff, %s missing in old' % key)
            print(old_osm.stedsnr[key][0])

    for key in new_stedsnr:
        if key not in old_stedsnr:
            print('Diff, %s missing in new' % key)
            print(new_osm.stedsnr[key][0])

    print('\n=== Tagging differences ===\n')
    stedsnr = set(old_stedsnr).intersection(new_stedsnr)

    for key in stedsnr:
        old = old_osm.stedsnr[key][0]
        new = new_osm.stedsnr[key][0]

        limit_distance = 1e-5 # FIXME: resonable?
        old_lat, old_lon = float(old.attribs['lat']), float(old.attribs['lon'])
        new_lat, new_lon = float(new.attribs['lat']), float(new.attribs['lon'])
        if abs(old_lat - new_lat) > limit_distance or abs(old_lon - new_lon) > limit_distance:
            print('Diff in position %s old [%s, %s] != new [%s, %s]' % (key, old_lat, old_lon, new_lat, new_lon))
            
        for tag_key in old.tags:
            if tag_key not in new.tags:
                print('Diff %s, %s missing in new:' % (key, tag_key))
                print(' old[%s] = %s\n' % (tag_key, old.tags[tag_key]))
        for tag_key in new.tags:
            if tag_key not in old.tags:
                print('Diff %s, %s missing in old:' % (key, tag_key))
                print(' new[%s] = %s\n' % (tag_key, new.tags[tag_key]))

        common_tags = set(old.tags.keys()).intersection(new.tags.keys())
        for tag_key in common_tags:
            if tag_key in ('ssr:date', ):
                continue # don't care
            
            o, n = new.tags[tag_key], old.tags[tag_key]
            if o != n:
                print('Diff %s:\n old[%s] = %s\n new[%s] = %s\n' % (key, tag_key, o, tag_key, n))
                
