# Standard library imports:
import json
from collections import defaultdict
import logging
logger = logging.getLogger('utility_to_osm.ssr2')

# Shared helper function import:
import utility_to_osm.file_util as file_util
import utility_to_osm.argparse_util as argparse_util

# third party
import osmapis
import openpyxl

# this project
from ssr2_split import copy_osm_element

def read_tags(filename):
    wb = openpyxl.load_workbook(filename=filename, data_only=True,
                                read_only=True)
    ws = wb.worksheets[0]
    rows = ws.rows

    header = rows.next()
    header = [item.value for item in header]
    #print header
    ix_hovedgruppe = header.index('SSR2 kategori')
    ix_type = header.index('SSR2 navnetype')
    ix_tag = header.index('tag')#.index('som tag')
    #ix_fixme = header.index('fixme')

    output = list()
    for row in rows:
        tags = dict()
        tags['ssr:hovedgruppe'] = row[ix_hovedgruppe].value
        tags['ssr:type'] = row[ix_type].value
        tags['tags'] = row[ix_tag].value
        #tags['tags'] += row[ix_tillegg].value
        #if row[ix_fixme].value != '':
        # if row[ix_fixme].value is not None:
        #     tags['tags'] += ';' + row[ix_fixme].value
        
        output.append(tags)
        #for item in row:
        #    print item.column
        #break
        #pass
        #print row

    return output

def tags_to_dict(table):
    output = defaultdict(dict)             # key is ssr:hovedgruppe + '-'  + ssr:type
    for row in table:
        key = ''
        # if row['ssr:hovedgruppe'] is not None:
        #     key += row['ssr:hovedgruppe'].lower()
        if row['ssr:type'] is not None:
            key += row['ssr:type'].lower()

        tags = dict()
        if row['tags'] is not None:
            sp = row['tags'].split(';')
            for item in sp:
                item = item.strip()
                if item == '': continue
                
                try:
                    ix_split = item.index('=')
                except ValueError:
                    raise ValueError('equal sign not found in tag = "%s"' % item)
                
                tag_key, value = item[:ix_split].strip(), item[ix_split+1:].strip()
                logger.debug('%s: "%s" = "%s"', key, tag_key, value)
                if tag_key != '' and value != '':
                    tags[tag_key] = value
        
        output[key] = tags
        
    return dict(output)

def replace_tags(filename_in, conversion_dict, include_empty=False, group_overview=None):
    if group_overview is None:
        group_overview = defaultdict(list)
    
    filename_base = filename_in.replace('.osm', '')
    filename_out = '%s-%s.osm' % (filename_base, 'tagged')
    filename_out_notTagged = '%s-%s.osm' % (filename_base, 'NotTagged')

    content = file_util.read_file(filename_in)
    osm = osmapis.OSM.from_xml(content)
    osm_new = osmapis.OSM()
    osm_new_notTagged = osmapis.OSM()

    for item in osm:
        item.added_to_osm_new = False
        key = ''
        ssr_hovedgruppe = None
        ssr_type = None
        # if 'ssr:hovedgruppe' in item.tags:
        #     ssr_hovedgruppe = item.tags['ssr:hovedgruppe']
        #     key += ssr_hovedgruppe.lower()
        if 'ssr:type' in item.tags:
            ssr_type = item.tags['ssr:type']
            key += ssr_type.lower()

        group_overview_key = ','.join([item.tags.get('ssr:hovedgruppe', ''),
                                       item.tags.get('ssr:gruppe', ''),
                                       item.tags.get('ssr:type', '')])
        group_overview_row = group_overview[group_overview_key]
        if len(group_overview_row) == 0: # first hit
            # [item count, tags]
            group_overview_row = [0, '']
        group_overview_tags = list()

        if key != '' and key in conversion_dict:
            tags = conversion_dict[key]
            # if item.tags['name'] == 'Nord-Noreg;Nord-Norge':
            #     print exclude_empty, len(tags) != 0, tags
            #     exit(1)
            if include_empty or len(tags) != 0:
                new_tags = dict(item.tags)
                # Moved:
                # new_tags.pop('ssr:hovedgruppe', '')
                # new_tags.pop('ssr:gruppe', '')
                # new_tags.pop('ssr:type', '')
                # new_tags.pop('ssr:sorting', '')
                #new_tags.pop('ssr:stedsnr', '')
                # new_tags.pop('ssr:date', '')

                #new_tags.update(tags)
                for key in sorted(tags.keys()):
                    if key in new_tags:    # hmm, vops?
                        if key == 'fixme': # ok, append
                            new_tags[key] = '%s; %s' % (new_tags[key], tags[key])
                        else:
                            raise ValueError('Overwritting tag[%s] = %s not allowed' % (key, tags[key]))
                    else:
                        new_tags[key] = tags[key]
                    # Add to overview table
                    if ' ' in tags[key]:
                        group_overview_tags.append('%s="%s"' % (key, tags[key]))
                    else:
                        group_overview_tags.append('%s=%s' % (key, tags[key]))
                    
                item.tags = new_tags # NOTE: inplace!
                #osm_new.add(item)
                item.added_to_osm_new = True
                copy_osm_element(osm, osm_new, item)
            else:
                logger.info('ssr:type = %s found in conversion table, but without tags', ssr_type)
        else:
            if ssr_type is not None:
                logger.warning('ssr:type = %s not found in conversion table', ssr_type)
        
        if not(item.added_to_osm_new):
            copy_osm_element(osm, osm_new_notTagged, item)

        group_overview_row[0] += 1
        s = ' '.join(group_overview_tags)
        if len(group_overview_row[1]) != 0 and group_overview_row[1] != s:
            raise ValueError('Vops: different tags for the same group overview key: %s != %s' % (s, group_overview_row[1]))
        group_overview_row[1] = s
        group_overview[group_overview_key] = group_overview_row
    
    if len(osm_new) != 0:
        osm_new.save(filename_out)
    if len(osm_new_notTagged) != 0:
        osm_new_notTagged.save(filename_out_notTagged)

    return filename_out

def get_conversion(excel_filename= 'data/Tagging tabell SSR2.xlsx'):
    table = read_tags(excel_filename)

    # for row in table:
    #     print row

    d = tags_to_dict(table)

    # for key in d:
    #     print key, d[key]
    return d
    
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='')
    argparse_util.add_verbosity(parser, default=logging.DEBUG)

    parser.add_argument('filename', help='specify filename to replace osm tags')
    
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)

    # 1) Get conversion:
    d = get_conversion(excel_filename = 'data/Tagging tabell SSR2.xlsx')
    with open('data/ssr2_tags.json', 'w') as f:
        json.dump(d, f)

    # 2) Apply to filename
    replace_tags(args.filename, d)
