import os
import logging
logger = logging.getLogger('utility_to_osm.ssr2.osm')

import utility_to_osm.kommunenummer as kommunenummer
import utility_to_osm.argparse_util as argparse_util
import utility_to_osm.overpass_helper as overpass_helper

global kommuneNr_2_relationId
kommuneNr_2_relationId = dict()

def overpass_stedsnr_in_relation(relation_id, cache_filename,
                            old_age_days = 14,
                            root_template = '',
                            query_template_filename = 'query_template.xml',):
    """Queries OSM for all ssr:stedsnr in the given relation-id (say a single Kommune, or the entire country)"""
    query_template_filename = os.path.join(root_template, query_template_filename)
    
    query = overpass_helper.get_xml_query(query_template_filename,
                                         relation_id=relation_id, use='relation')
    osm = overpass_helper.overpass_xml(xml=query, old_age_days=old_age_days,
                                       cache_filename=cache_filename)
    return osm

def overpass_stedsnr_in_kommunenr(n, cache_filename, cache_dir, **kwargs):
    """Calls overpass_stedsnr_in_relation after converting from kommune-nr to osm-relation-id"""
    global kommuneNr_2_relationId
    if len(kommuneNr_2_relationId) == 0:
        print('getting cache')
        kommuneNr_2_relationId = kommunenummer.get_osm_kommune_ids(cache_dir=cache_dir)
    
    relation_id = kommuneNr_2_relationId[int(n)]
    return overpass_stedsnr_in_relation(relation_id, cache_filename, **kwargs)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='')
    argparse_util.add_verbosity(parser, default=logging.INFO)

    parser.add_argument('--output', default='output', 
                        help='Output root directory.')

    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)
    
    kommuneNr_2_name, _ = kommunenummer.kommunenummer(cache_dir=args.output)
    kommuneNr_2_relationId = kommunenummer.get_osm_kommune_ids(cache_dir=args.output)
    for key in kommuneNr_2_name:
        try:
            kommuneNr_2_name[key], kommuneNr_2_relationId[key]
            logger.info('kommune_nr = %s, kommune_name = %s, osm_relation_id = %s',
                        key, kommuneNr_2_name[key], kommuneNr_2_relationId[key])
        except:
            logger.error('Error key=%s', key)
        
    # for key, value in kommuneNr_2_relationId.items():
    #     print(key, value)

    for key in sorted(kommuneNr_2_relationId.keys()):
        # relation_id = kommuneNr_2_relationId[key]
        kommune_nr_str = '%04d' % key
        cache_filename = os.path.join(args.output,
                                      kommune_nr_str,
                                      '%s-osmStedsnr.osm' % kommune_nr_str)
        # overpass_stedsnr = overpass_stedsnr_in_relation(relation_id, cache_filename)
        overpass_stedsnr = overpass_stedsnr_in_kommunenr(kommune_nr_str, cache_filename, cache_dir=args.output)
        print('%s items in osm = %s' % (kommune_nr_str, len(overpass_stedsnr)))
