# splits the given .osm file into seperate .osm files for each "SSR2 kategory" = ssr:hovedgruppe
import logging
logger = logging.getLogger('utility_to_osm.ssr2_split')

import utility_to_osm.argparse_util as argparse_util
import utility_to_osm.file_util as file_util

import osmapis

def copy_osm_element(osm, osm_new, item, recursion=0):
    if recursion > 100:
        raise Exception('Somethings fishy, copy_osm_element(..., recursion = %s)' % recursion)

    # If relation or way, copy children:
    if isinstance(item, osmapis.Relation):
        for item_child in item.members:
            raise NotImplemented('Sorry, no relation support')
            copy_osm_element(osm, osm_new, item_child, recursion = recursion + 1)
    elif isinstance(item, osmapis.Way):
        for item_node_id in item.nds:
            item_child = osm.nodes[item_node_id]
            copy_osm_element(osm, osm_new, item_child, recursion = recursion + 1)
    elif isinstance(item, osmapis.Node):
        pass
    else:
        raise ValueError('Expected Node, Way or Relation, got = %s' % type(item))

    osm_new.add(item)


def osm_split(filename_in, split_key='ssr:hovedgruppe'):
    content = file_util.read_file(filename_in)
    osm = osmapis.OSM.from_xml(content)

    # Find unique list of values to split by
    split_values = set()
    for item in osm:
        if split_key in item.tags:
            split_values.add(item.tags[split_key])

    filenames = list()
    for split in split_values:
        osm_new = osmapis.OSM()
        for item in osm:
            if split_key in item.tags and item.tags[split_key] == split: # Match
                copy_osm_element(osm, osm_new, item)

        # Save:
        if len(osm_new) != 0:
            filename_out = filename_in.replace('.osm', '')
            filename_out = filename_out.replace('-all', '')
            filename_out = '%s-%s.osm' % (filename_out, split)
            osm_new.save(filename_out)
            filenames.append(filename_out)

    return filenames

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='')
    argparse_util.add_verbosity(parser, default=logging.INFO)

    parser.add_argument('filename', help='filename to split')

    args = parser.parse_args()
    osm_split(args.filename)
