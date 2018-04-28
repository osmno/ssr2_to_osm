import re

import osmapis
import openpyxl


filename_gammel = '/Users/ob/Google Drive/Stedsnavn/Nordland_gammel.osm'
filename_gammel_converted = '/Users/ob/Google Drive/ssr2_to_osm_data/Nordland_gammel_converted.osm'
conversion_table_filename = '/Users/ob/Google Drive/Stedsnavn/Konvertering fra SSR1_id til SSR2_id.xlsx'
filenames_new = ['/Users/ob/Programming/Python/osm/ssr2_to_osm/html/data/1837/1837.osm',
                 '/Users/ob/Programming/Python/osm/ssr2_to_osm/html/data/1838/1838.osm']
tags_to_remove = ['no-kartverket-ssr:date', 'no-kartverket-ssr:objid', 'no-kartverket-ssr:url']
tags_to_ignore_in_comparision = ['fixme', 'place']

with open(filename_gammel, 'r') as f:
    osm_g = osmapis.OSM.from_xml(f.read())
# Create dictionary with 'no-kartverket-ssr:objid' as key
osm_g_dict = dict()
for item_g in osm_g:
    # if 'no-kartverket-ssr:objid' in item_g.tags:
    #     value = item_g.tags['no-kartverket-ssr:objid']
    #     osm_g_dict[value] = item_g
    if 'no-kartverket-ssr:url' in item_g.tags:
        url = item_g.tags['no-kartverket-ssr:url']
        reg = re.search('enhet=(\d+)', url)
        if reg:
            value = reg.group(1)
            osm_g_dict[value] = item_g
        else:
            print('error: unable to find enhet in url = %s', url)

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

for ssrid in osm_g_dict:
    if ssrid in ssrid_2_stedsnummer:
        converted_stedsnummer = ssrid_2_stedsnummer[ssrid]
        if len(converted_stedsnummer) == 1:
            new_tag = converted_stedsnummer[0]
            osm_g_dict[ssrid].tags['ssr:stedsnr'] = new_tag
            
            for rm_tag in tags_to_remove:
                item_g.tags.pop(rm_tag, '')

for filename in filenames_new:
    with open(filename, 'r') as f:
        osm_new = osmapis.OSM.from_xml(f.read())

    for item in osm_new:
        if 'ssr:stedsnr' in item.tags:
            new_tag = item.tags['ssr:stedsnr']
            if new_tag in stedsnummer_2_ssrid:
                old_tag = stedsnummer_2_ssrid[new_tag]
            else:
                print('conversion not found for ssr:stedsnr = %s' % (new_tag))
                continue

            fixme = []
            if len(old_tag) > 1:
                fixme.append('duplicate conversion stedsnummer found in conversion table, fix manually')
                for value in old_tag:
                    fixme.append('stedsnummer = %s - ssrid = %s' % (value, new_tag))

            old_tag = old_tag[0]
            
            # Look for old_tag in osm_g
            if old_tag in osm_g_dict:
                item_g = osm_g_dict[old_tag] # found it
                item_g.tags['ssr:stedsnr'] = new_tag

                for tag in item.tags:
                    if not(tag.startswith('ssr')) and (tag not in tags_to_ignore_in_comparision):
                        fixme.extend(compare_tag(item_g.tags, item.tags, tag))
                
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
