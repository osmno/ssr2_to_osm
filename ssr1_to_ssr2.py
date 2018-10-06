import re
from collections import defaultdict

import osmapis
import openpyxl


filename_gammel = '/Users/ob/Google Drive/Stedsnavn/Nordland_gammel.osm'
filename_gammel_converted = '/Users/ob/Google Drive/ssr2_to_osm_data/Nordland_gammel_converted.osm'
conversion_table_filename = '/Users/ob/Google Drive/Stedsnavn/Konvertering fra SSR1_id til SSR2_id.xlsx'
filenames_new = ['/Users/ob/Programming/Python/osm/ssr2_to_osm/html/data/1837/1837.osm',
                 '/Users/ob/Programming/Python/osm/ssr2_to_osm/html/data/1838/1838.osm']

COMPARE_TAGS = False
# filename_gammel = '/Users/ob/Google Drive/Stedsnavn/Source_id_gammel.osm'
# filename_gammel_converted = '/Users/ob/Google Drive/ssr2_to_osm_data/Source_id_gammel_converted.osm'
# conversion_table_filename = '/Users/ob/Google Drive/Stedsnavn/Konvertering fra SSR1_id til SSR2_id.xlsx'
# filenames_new = list()
# for kommune_nr in (2022, 2023, 632, 631, 621, 623, 628, 627, 602, 625, 624, 604):
#     filenames_new.append('/Users/ob/Programming/Python/osm/ssr2_to_osm/html/data/%04d/%04d.osm' % (kommune_nr, kommune_nr))

tags_to_remove = ['no-kartverket-ssr:date', 'no-kartverket-ssr:objid', 'no-kartverket-ssr:url',
                  'source_id', 'source_ref']
tags_to_ignore_in_comparision = ['fixme', 'place']
tags_to_ignore_in_comparision.extend(tags_to_remove)

with open(filename_gammel, 'r') as f:
    osm_g = osmapis.OSM.from_xml(f.read())
# Create dictionary with source_id as key and a list of elements with that key
osm_g_dict = defaultdict(list)
for item_g in osm_g:
    ref_from_url = None
    # if 'no-kartverket-ssr:objid' in item_g.tags:
    #     value = item_g.tags['no-kartverket-ssr:objid']
    #     osm_g_dict[value] = item_g
    if 'no-kartverket-ssr:url' in item_g.tags:
        url = item_g.tags['no-kartverket-ssr:url']
        reg = re.search('enhet=(\d+)', url)
        if reg:
            value = reg.group(1)
            osm_g_dict[value].append(item_g)
        else:
            print('error: unable to find enhet in url = %s', url)
    if 'source_ref' in item_g.tags:
        # fixme: copy of above
        url = item_g.tags['source_ref']
        reg = re.search('enhet=(\d+)', url)
        if reg:
            ref_from_url = reg.group(1) # Used below in assertion/sanity check
        else:
            print('error: unable to find enhet in url = %s', url)
        
    if 'source_id' in item_g.tags:
        value = item_g.tags['source_id']
        if ref_from_url != None:
            if value != ref_from_url:
                print('expected enhet from url and source_id to be identical "%s" != "%s", skipping' % (value, ref_from_url))
                continue
        
        osm_g_dict[value].append(item_g)

print('read osm file, len(elements) = %s, %s items with no-kartverket-ssr:objid' % (len(osm_g), len(osm_g_dict)))

wb = openpyxl.load_workbook(filename=conversion_table_filename, data_only=True,
                                read_only=True)
ws = wb.worksheets[0]
rows = ws.rows

header = rows.next()
header = [item.value for item in header]
print('excel conversion header = %s' % header)
ix_ssrid = header.index('ssrid') # no-kartverket-ssr:objid
ix_stedsnummer = header.index('stedsnummer') # ssr:stedsnr
ix_stedsnavnnummer = header.index('stedsnavnnummer') # not in new .osm files, ignore

def append_to_conversion_dict(conversion, key, value):
    if key.strip() == '' or value.strip() == '':
        return

    if key in conversion and value not in conversion[key]:
        #print('warning')
        conversion[key].append(value)
    else:
        conversion[key] = [value]


stedsnummer_2_ssrid = dict()
ssrid_2_stedsnummer = dict()
for row in rows:
    stedsnummer = str(row[ix_stedsnummer].value)
    ssrid = str(row[ix_ssrid].value)

    append_to_conversion_dict(stedsnummer_2_ssrid, key=stedsnummer, value=ssrid)
    append_to_conversion_dict(ssrid_2_stedsnummer, key=ssrid, value=stedsnummer)

#print('excel conversion elements = %s' % len(conversion))

def compare_tag(osm_item, ssr2_item, key):
    fixme = []
    missing = False
    if key not in osm_item:
        fixme.append('osm: %s = "%s" missing from old import' % (key, ssr2_item[key]))
        missing = True
    if key not in ssr2_item:
        fixme.append('ssr2: %s = "%s" missing from new import' % (key, osm_item[key]))
        missing = True
        
    if not(missing) and osm_item[key] != ssr2_item[key]:
        fixme.append('value differs osm: %s = "%s" != ssr2: %s = "%s"' % (key, osm_item[key], key, ssr2_item[key]))

    return fixme

def remove_names_already_present(list_of_names, dct):
    list_of_names = list(list_of_names)
    for key in dct:
        if key.endswith('name'):
            try:
                ix = list_of_names.index(dct[key])
                del list_of_names[ix]
            except ValueError:
                pass
    return list_of_names

for ssrid in osm_g_dict:
    for item_g in osm_g_dict[ssrid]:
    #item_g = osm_g_dict[ssrid]
        if ssrid in ssrid_2_stedsnummer:
            converted_stedsnummer = ssrid_2_stedsnummer[ssrid]
            if len(converted_stedsnummer) == 1:
                new_tag = converted_stedsnummer[0]
                item_g.tags['ssr:stedsnr'] = new_tag
                item_g.attribs['action'] = 'modify'

                for rm_tag in tags_to_remove:
                    item_g.tags.pop(rm_tag, '')
            else:
                print('Multiple conversions found for ssrid = %s, %s' % (ssrid, converted_stedsnummer))
        else:
            print('No conversion found for ssrid = %s' % ssrid)

for filename in filenames_new:
    with open(filename, 'r') as f:
        osm_new = osmapis.OSM.from_xml(f.read())

    for item in osm_new:
        if 'ssr:stedsnr' in item.tags:
            new_tag = item.tags['ssr:stedsnr']
            if new_tag in stedsnummer_2_ssrid:
                old_tags = stedsnummer_2_ssrid[new_tag]
            else:
                print('conversion not found for ssr:stedsnr = %s' % (new_tag))
                continue

            fixme = []
            if len(old_tags) != 1:
                #fixme.append('duplicate conversion stedsnummer found in conversion table, fix manually')
                print('duplicate conversion stedsnummer found in conversion table:')
                for value in old_tags:
                    print('stedsnummer = %s - ssrid = %s' % (value, new_tag))
                    #fixme.append('stedsnummer = %s - ssrid = %s' % (value, new_tag))
                
                #old_tag = ';'.join(old_tags)                    

            item_g_lst = list()                
            for old_tag in old_tags:
                # Look for old_tag in osm_g
                
                if old_tag in osm_g_dict:
                    items_g = osm_g_dict[old_tag] # found it
                    item_g_lst.extend(items_g)
                
            if len(item_g_lst) == 0:
                continue
            elif len(item_g_lst) != 1:
                fixme.append('duplicate conversion stedsnummer found in conversion table, fix manually')
                for item_g in item_g_lst:
                    fixme.append('stedsnummer = %s - ssrid = %s' % (value, new_tag))

            for item_g in item_g_lst:
                item_g.tags['ssr:stedsnr'] = new_tag
                item_g.attribs['action'] = 'modify'

                # Get list of alt_names and names in ssr2
                names = list()
                for name_key in ('name', 'alt_name'):
                    try:
                        value = item.tags[name_key]
                        value_split_semi = value.split(';')
                        value_split = list()
                        for semi_item in value_split_semi:
                            value_split.extend(semi_item.split(' - '))
                        names.extend(value_split)
                    except KeyError:
                        pass
                # Remove names already imported:
                names = remove_names_already_present(names, item_g.tags)

                # Only add if missing alt_name
                if 'alt_name' not in item_g.tags and len(names) != 0:
                    # Ok, add to alt_name:
                    item_g.tags['alt_name'] = ';'.join(names)

                # Add loc_name and old_name if missing
                for name_key in ('loc_name', 'old_name'):
                    if name_key not in item_g.tags:
                        try:
                            value = item.tags[name_key]
                            # Ensure value not already in any other name tag
                            value_lst = remove_names_already_present([value], item_g.tags)
                            if len(value_lst) == 1:
                                # ok, guess we are safe
                                item_g.tags[name_key] = value_lst[0]
                        except KeyError:
                            pass

                if COMPARE_TAGS:
                    for tag in item.tags:
                        if not(tag.startswith('ssr')) and (tag not in tags_to_ignore_in_comparision):
                        #if tag.endswith(('name', 'alt_name')):
                            fixme.extend(compare_tag(item_g.tags, item.tags, tag))
                # for tag in item_g.tags:
                #     if tag.endswith(('name', 'alt_name')):
                #         fixme.extend(compare_tag(item_g.tags, item.tags, tag))

                if len(fixme) != 0:
                    prev_fixme = item_g.tags.pop('fixme', '')
                    if prev_fixme != '':
                        fixme.insert(0, prev_fixme)

                    item_g.tags['fixme'] = ';'.join(fixme)

                for rm_tag in tags_to_remove:
                    item_g.tags.pop(rm_tag, '')

            else:
                #print('')
                continue
            
            # for item_g in osm_g:
            #     if 'no-kartverket-ssr:objid' in item_g.tags:
            #         item_g.tags['no-kartverket-ssr:objid']
                    
osm_g.save(filename_gammel_converted)
