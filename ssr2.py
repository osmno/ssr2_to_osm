#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import csv
import json
import codecs
open = codecs.open
import datetime
import logging
logger = logging.getLogger('utility_to_osm.ssr2')

from bs4 import BeautifulSoup
#import requests

# Shared helper function import:
import utility_to_osm
import utility_to_osm.overpass_helper as overpass_helper
import utility_to_osm.file_util as file_util
import utility_to_osm.gentle_requests as gentle_requests
import utility_to_osm.argparse_util as argparse_util
from utility_to_osm.kommunenummer import kommunenummer, to_kommunenr
from utility_to_osm.csv_unicode import UnicodeWriter

# third party:
import osmapis
import pyproj

# This project
import ssr2_split
import ssr2_tags

def add_file_handler(filename='warnings.log'):
    fh = logging.FileHandler(filename, mode='w')
    #fh.setLevel(logging.WARNING)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return fh

def parse_gml_point(point):
    epsg = point['srsname']
    projection = pyproj.Proj(init=epsg)#'epsg:%s' % srid)
    #print 'POINT', point
    utm33 = point.find('gml:pos').text.split()
    lon, lat = projection(utm33[0], utm33[1], inverse=True)

    gml_id = point['gml:id']
    
    return lon, lat, gml_id

def parse_sortering(entry):
    """Extract sorterings-kode from xml tags app:sortering1kode and app:sortering2kode"""
    viktighet1 = entry.find('app:sortering1kode').text
    viktighet2 = entry.find('app:sortering2kode').text
    viktighet1 = viktighet1.replace('viktighet', '')
    viktighet2 = viktighet2.replace('viktighet', '')
    sorting = viktighet1 + viktighet2
    return sorting

def parse_stedsnavn(entry, return_only=('godkjent', 'internasjonal', 'vedtatt', 'vedtattNavneledd'),
                    silently_ignore=('historisk', ), additional_tags=None):
    """
     Structure seems to be
    <app:sted>
      <app:stedsnavn> 
        <app:Stedsnavn> "NAME1" </app:stedsnavn>
      </app:stedsnavn>
      <app:stedsnavn> 
        <app:Stedsnavn> "NAME2" </app:stedsnavn>
      </app:stedsnavn>
    <app:sted>
    note the nested <app:stedsnavn><app:stedsnavn>...

    Returns a list of dictionaries for each name, where skrivemåte is 
    in return_only, default:
    ('godkjent', 'internasjonal', 'vedtatt', 'vedtattNavneledd')
    Items not in silently_ignore will be logged.
    """
    if additional_tags is None:
        additional_tags = dict()
    additional_tags['name:language_priority'] = entry.find('app:spr').text # språkprioritering

    parsed_names = list()
    for names in entry.find_all('app:stedsnavn', recursive=False):
        names_nested = names.find_all('app:stedsnavn', recursive=False)
        assert len(names_nested) == 1, 'Vops: expected this to only be 1 element %s' % names
        names = names_nested[0]

        language = names.find('app:spr').text # FIXME: språk
        name_status = names.find('app:navnestatus').text
        #name_case_status = names.find('app:navnesakstatus') # seems to only be 'ubehandlet'
        eksonym = names.find('app:eksonym').text
        stedsnavnnummer = names.find('app:stedsnavnnummer').text
        
        #print 'NAME', name.prettify()
        #FIXME: I would expect this to work, but it returns None: skrivem = names.find(u'app:skrivemåte')
        for skrivem in names.find_all('app:skrivem', recursive=False):
            skrivem_nested = skrivem.find_all('app:skrivem', recursive=False)
            assert len(skrivem_nested) == 1, 'Vops: expected this to only be 1 element %s' % skrivem
            skrivem = skrivem_nested[0]

            #print 'SKRIVEM', skrivem.prettify()
            if additional_tags is None:
                tags = dict()
            else:
                tags = dict(additional_tags) # start with the additional tags
            
            tags['name'] = skrivem.find('app:langnavn').text
            #print skrivem.prettify()
            tags['name:language'] = language
            tags['name:name_status'] = name_status
            tags['name:eksonym'] = eksonym
            tags['name:stedsnavnnummer'] = stedsnavnnummer
            #tags['name:order'] = skrivem.find('app:rekkef').text
            priority_spelling = skrivem.find('app:prioritertskrivem').text # app:prioritertSkrivemåte
            if priority_spelling == u'true':
                priority_spelling = True
            elif priority_spelling == u'false':
                priority_spelling = False
            else:
                raise ValueError('Expected priority_spelling to to "true" or "false" not "%s"', priority_spelling)
            
            tags['name:priority_spelling'] = priority_spelling

            # Date:
            date = skrivem.find('app:oppdateringsdato').text
            try:
                date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f') # to python object
            except ValueError:
                date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S') # to python object
                
            date_str = date_python.strftime('%Y-%m-%d') # to string
            tags['ssr:date'] = date_str
            order_spelling = int(skrivem.find('app:skrivem').text)
            tags['name:order_spelling'] = order_spelling

            # FIXME: BUG:
            #status = skrivem.find('app:skrivemåtestatus').text
            status = skrivem.find_all('app:skrivem')[1].text
            tags['name:spelling_status'] = status
            
            if status in return_only:
                parsed_names.append((order_spelling, tags))
            else:
                if not(status in silently_ignore):
                    logger.info('ignoring non approved status = "%s" name = "%s"',
                                status, tags['name'])
            
    parsed_names_sort = sorted(parsed_names)
    parsed_names_tags = list()
    for order_spelling, tags in parsed_names_sort:
        parsed_names_tags.append(tags)

    return parsed_names_tags

def find_all_languages(*args):
    languages = set()
    for arg in args:
        for item in arg:
            languages.add(item['name:language'])
    return languages

def ssr_language_to_osm_key(ssr_lang):
    # fixme: replace with a defaultDict with None as return.
    ssr_language_to_osm = {'nor': 'no',
                           'smj': 'smj',
                           'sme': 'se',
                           'sma': 'sma',
                           'fkv': 'fkv'}
    if ssr_lang in ssr_language_to_osm:
        return ssr_language_to_osm[ssr_lang]
    else:
        return None

def add_name_tags(multi_names, stedsnr, tags, language, language_priority,
                  parsed_names, tag_key='name'):
    # Starts by sorting out so that parsed_names only contain elements in 'language',
    # depending on language != 'nor' or language_priority != 'nor' additional tag_key:lang keys will be added.
    # Tag key == 'name' will be treated differently as only a single name is allowed, additional names are then added to alt_name.
    ix = 0
    parsed_names = list(parsed_names)
    while ix < len(parsed_names):
        if parsed_names[ix]['name:language'] != language:
            del parsed_names[ix]
        else:
            ix += 1

    tag_key_lang = ''
    logger.debug('add_name_tags(tag_key=%s, language=%s, language_priority=%s',
                 tag_key, language, language_priority)
    if not(language == 'nor' and language_priority.startswith('nor')):
        l = ssr_language_to_osm_key(language)
        if l is None:
            logger.error('unrecognized ssr language = "%s"', language)
            return None
        
        tag_key_lang = '%s:%s' % (tag_key, l)
        #print tag_key_lang

    if tag_key != 'name' and tag_key_lang != '':
        tag_key = '' # only use tag_key_lang
    
    #exit(1)

    def add_name_tag(tags, language, language_priority,
                     tag_key, tag_key_lang,
                     names):
        logger.debug('add_name_tag(language=%s, language_priority=%s, tag_key=%s, tag_key_lang=%s,names=%s)',
                     language, language_priority,
                     tag_key, tag_key_lang,
                     names)
        if tag_key != '' and language_priority.startswith(language):
            assert tag_key not in tags, 'Vops, tag already set tags["%s"] = "%s"' % (tag_key, tags[tag_key])
            # simple case, language and language priority match
            tags[tag_key] = names
            logger.debug('add_name_tag tags[%s] = %s', tag_key, names)
        if tag_key_lang != '':
            # Add additional :lang key with possibly duplicate info
            assert tag_key_lang not in tags, 'Vops, lang tag already set tags["%s"] = "%s"' % (tag_key_lang,
                                                                                               tags[tag_key_lang].encode('utf-8'))
            tags[tag_key_lang] = names
            logger.debug('add_name_tag lang tags[%s] = %s', tag_key_lang, names)

    # How many names did we get?
    if len(parsed_names) == 0:
        #logger.debug('no names found for language = %s and key = %s', language, tag_key)
        pass
    elif len(parsed_names) == 1:
        add_name_tag(tags, language, language_priority,
                     tag_key, tag_key_lang, parsed_names[0]['name'])
            
        tags['ssr:date'] = parsed_names[0]['ssr:date']
    else:
        multi_names[stedsnr] = parsed_names

        used_names = list()

        if tag_key == 'name':
            # 1: find all priority spelling
            name_pri_spelling = list()
            for item in parsed_names:
                if item['name:priority_spelling']:
                    name_pri_spelling.append(item['name'])

            # 1.1 How many did we get?
            if len(name_pri_spelling) == 1: # Single item?
                # Hurray!
                names = name_pri_spelling[0]
                used_names.append(name_pri_spelling[0])
            elif len(name_pri_spelling) != 0:
                # Vops: Multiple priority spellings
                names = ";".join(name_pri_spelling)
                used_names.extend(name_pri_spelling)
                logger.error('ssr:stedsnr = %s, Adding multiple names to name tag, this is not OK! name = "%s"',
                             tags['ssr:stedsnr'], names)
                tags['fixme'] = 'multiple name tags, choose one and add the other to alt_name'
            else:
                # Vops: No priority spelling
                #warning not error
                names = None
                logger.warning('ssr:stedsnr = %s: No priority spelling found, using first alt_name' % tags['ssr:stedsnr'])

            if names is not None:
                add_name_tag(tags, language, language_priority,
                             tag_key, tag_key_lang, names)

            # 2: find all remaining names
            alt_names = list()
            for item in parsed_names:
                if item['name'] not in used_names:
                    alt_names.append(item['name'])

            # 2.1 use first alt item as name if we are lacking a name
            if language_priority.startswith(language): # 'main' language only
                if len(alt_names) != 0 and ('name' not in tags):
                    logger.debug('Lacking name, using alt_name. tag_key = %s, tag_key_lang = %s',
                                 tag_key, tag_key_lang)
                    #tags[tag_key] = alt_names[0]
                    add_name_tag(tags, language, language_priority,
                                 tag_key, tag_key_lang, alt_names[0])

                    del alt_names[0]

            # 2.1 add to alt_name
            if len(alt_names) != 0:
                names = ";".join(alt_names)
                #tags['alt_' + tag_key] = names
                tag_key_lang_alt = ''
                if tag_key_lang != '':
                    tag_key_lang_alt = 'alt_' + tag_key_lang
                tag_key_alt = ''
                if tag_key != '':
                    tag_key_alt = 'alt_' + tag_key
                
                add_name_tag(tags, language, language_priority,
                             tag_key_alt, tag_key_lang_alt, names)

        else: # tag_key != 'name'
            names = list()
            for item in parsed_names:
                names.append(item['name'])

            names = ";".join(names)
            #tags[tag_key] = names
            add_name_tag(tags, language, language_priority,
                         tag_key, tag_key_lang, names)
    return True
            
def parse_geonorge(soup, create_multipoint_way=False):
    # create OSM object:
    osm = osmapis.OSM()
    multi_names = dict()
    for entry in soup.find_all('app:sted'):
        #print 'STED', entry.prettify()
        tags = dict()
        attribs = dict()
        stedsnr = entry.find('app:stedsnummer').text
        tags['ssr:stedsnr'] = stedsnr

        # Active?
        active = entry.find('app:stedstatus').text
        if active != 'aktiv':
            logger.info('ssr:stedsnr = %s not active = "%s". Skipping...', stedsnr, active)
            continue
        
        # tags['ssr:navnetype'] = entry.find('app:navneobjektgruppe').text
        # tags['ssr:navnekategori'] = entry.find('app:navneobjekthovedgruppe').text
        tags['ssr:hovedgruppe'] = entry.find('app:navneobjekthovedgruppe').text
        tags['ssr:gruppe'] = entry.find('app:navneobjektgruppe').text
        tags['ssr:type'] = entry.find('app:navneobjekttype').text

        # # Sorting:
        # sortering = parse_sortering(entry)
        # if sortering != '':
        #     tags['ssr:sorting'] = sortering

        # fixme: parse ssr:navnetype and ssr:navnekategori into proper openstreetmap tag(s)

        return_only = ('godkjent', 'internasjonal', 'vedtatt', 'vedtattNavneledd', 'privat', 'uvurdert')
        parsed_names = parse_stedsnavn(entry, return_only=return_only,
                                       silently_ignore=['historisk', 'foreslått'])
        if len(parsed_names) == 0:
            logger.warning('ssr:stedsnr = %s: No valid names found, skipping', stedsnr)
            continue
        else:
            language_priority = parsed_names[0]['name:language_priority'] # this is equal for all elements in parsed_names

        silently_ignore = list(return_only)
        silently_ignore.append('foreslått')
        parsed_names_historic = parse_stedsnavn(entry, return_only=['historisk'],
                                                 silently_ignore=silently_ignore)
        silently_ignore = list(return_only)
        silently_ignore.append('historisk')
        parsed_names_locale =    parse_stedsnavn(entry, return_only=['foreslått'],
                                                 silently_ignore=silently_ignore)

        languages = find_all_languages(parsed_names, parsed_names_historic, parsed_names_locale)
        if len(languages) != 1:
            logger.debug('ssr:stedsnr = %s, languages = %s', tags['ssr:stedsnr'], languages)
        
            
        for lang in languages:
            add_name_tags(multi_names, stedsnr, tags, language=lang, language_priority=language_priority,
                          tag_key='name', parsed_names=parsed_names)
            add_name_tags(multi_names, stedsnr, tags, language=lang, language_priority=language_priority,
                          tag_key='old_name', parsed_names=parsed_names_historic)
            add_name_tags(multi_names, stedsnr, tags, language=lang, language_priority=language_priority,
                          tag_key='loc_name', parsed_names=parsed_names_locale)

        if 'name' not in tags:
            languages = list(languages)
            # find first occurrence of name:xx, starting with priority language, then norwegian, then the rest
            language_priority_sp = language_priority.split('-')
            pri = language_priority_sp[0]
            pri2 = 'no'
            # we do not care if these are duplicated, as long as the priority language is first
            languages.insert(0, pri2)
            languages.insert(0, pri)

            for lang in languages:
                tag_key_lang = '%s:%s' % ('name', lang)
                if tag_key_lang in tags:
                    tags['name'] = tags[tag_key_lang]
                    break
        
        pos = entry.find('app:posisjon')
        positions = pos.find_all('gml:point')
        create_node = False
        if len(positions) == 0:
            logger.error('ssr:stedsnr = %s. No positions found, skipping',
                         tags['ssr:stedsnr'])
            continue
        elif len(positions) == 1:
            create_node = True
        else:
            if create_multipoint_way:
                nds = list()
                for ix, pos in enumerate(positions):
                    lon, lat, gml_id = parse_gml_point(pos)
                    attribs['lat'], attribs['lon'] = lat, lon
                    node = osmapis.Node(attribs=attribs,
                                    tags={'ssr:gml_id': gml_id, 'ssr:gml_nr': str(ix)})
                    osm.add(node)
                    nds.append(node.id)
                osm_element = osmapis.Way(tags=tags, nds=nds)
            else:
                logger.warning('ssr:stedsnr = %s has multiple (%s) positions, using the first one!',
                               tags['ssr:stedsnr'], len(positions))
                create_node = True

        if create_node:
            lon, lat, _ = parse_gml_point(positions[0])
            attribs['lat'], attribs['lon'] = lat, lon
            osm_element = osmapis.Node(attribs=attribs, tags=tags)
        
        osm.add(osm_element)

    return osm, multi_names

def main(kommunenummer, root='output', character_limit=-1, create_multipoint_way=False):
    if not(isinstance(kommunenummer, str)):
        raise ValueError('expected kommunenummer to be a string e.g. "0529"')

    # xml = file_util.read_file('ssr2_query_template.xml')
    # xml = xml.format(kommunenummer="0529")
    
    # url = 'http://wfs.geonorge.no/skwms1/wfs.stedsnavn50'
    # d = req.post(url, data=xml,
    #              headers={'contentType':'text/xml; charset=UTF-8',
    #                       'dataType': 'text'})
    # print d.text
    # soup = BeautifulSoup(d.text, 'lxml')
    
    url = 'http://wfs.geonorge.no/skwms1/wfs.stedsnavn50?VERSION=2.0.0&SERVICE=WFS&srsName=EPSG:25832&REQUEST=GetFeature&TYPENAME=Sted&resultType=results&Filter=%3CFilter%3E%20%3CPropertyIsEqualTo%3E%20%3CValueReference%20xmlns:app=%22http://skjema.geonorge.no/SOSI/produktspesifikasjon/Stedsnavn/5.0%22%3Eapp:kommune/app:Kommune/app:kommunenummer%3C/ValueReference%3E%20%3CLiteral%3E{kommunenummer}%3C/Literal%3E%20%3C/PropertyIsEqualTo%3E%20%3C/Filter%3E" --header "Content-Type:text/xml'
    url = url.format(kommunenummer=kommunenummer)

    folder = os.path.join(root, kommunenummer)
    xml_filename = os.path.join(folder, '%s-geonorge.xml' % kommunenummer)
    osm_filename = os.path.join(folder, '%s-all.osm' % kommunenummer)
    log_filename = os.path.join(folder, '%s.log' % kommunenummer)
    json_names_filename = os.path.join(folder, '%s-multi-names.json' % kommunenummer)
    csv_names_filename = os.path.join(folder, '%s-multi-names.csv' % kommunenummer)

    file_util.create_dirname(log_filename)
    add_file_handler(log_filename)

    # get xml:
    req = gentle_requests.GentleRequests()
    d = req.get_cached(url, xml_filename)
    # parse xml:
    soup = BeautifulSoup(d[:character_limit], 'lxml')
    osm, multi_names = parse_geonorge(soup, create_multipoint_way=create_multipoint_way)

    # Save result:
    # for item in osm:
    #     for key in item.tags:
    #         print key,
    #         print item.tags[key]
    #     print item
        
    osm.save(osm_filename)
    with open(json_names_filename, 'w', 'utf-8') as f:
        json.dump(multi_names, f)

    # https://stackoverflow.com/a/10373268/1942837
    multi_names_list = list()
    header = set()
    for key in multi_names.keys():
        for row in multi_names[key]:
            row = dict(row)
            row['ssr:stedsnr'] = key
            multi_names_list.append(row)
            header = header.union(row.keys())

    header = sorted(header)
    ix_sted = header.index('ssr:stedsnr')
    header[0], header[ix_sted] = header[ix_sted], header[0] # swap
    with open(csv_names_filename, 'w', 'utf-8') as f:
        w = csv.DictWriter(f, header)
        w.writer = UnicodeWriter(f, dialect='excel')
        w.writeheader()
        w.writerows(multi_names_list)

    return osm_filename

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='')
    argparse_util.add_verbosity(parser, default=logging.INFO)

    parser.add_argument('--output', default='output', 
                        help='Output root (working) directory. This tool will store files under <root>/<kommunenummer>/')
    parser.add_argument('--kommune', nargs='+', default=['ALL'], 
                        help='Specify one or more kommune (by kommune-number or kommune-name), or use the default "ALL" (slow!)')
    parser.add_argument('--character_limit', default=-1, type=int,
                        help='For quicker debugging, reduce the number of characters sent to the xml-parser, recommended --character_limit 100000 when playing around')
    parser.add_argument('--create_multipoint_way', default=False, action='store_true',
                        help='For debugging: create a osm-way for all elements that have multiple locations associated with it.')
    parser.add_argument('--not_split_hovedgruppe', default=False, action='store_true',
                        help='Do not create additional osm file copies, one for each "hovedgruppe"')
    parser.add_argument('--not_convert_tags', default=False, action='store_true',
                        help='Do not create additional osm file copies where ssr:hovedgruppe and ssr:type is used to translate to osm related tags')
    parser.add_argument('--not_remove_extra_tags', default=False, action='store_true',
                        help='Do not remove special ssr: keys that we do not want to import.')
    parser.add_argument('--include_empty_tags', default=False, action='store_true',
                        help='Do not remove nodes where no corresponding osm tags are found')
    
    
    args = parser.parse_args()
    #logging.basicConfig(level=args.loglevel)

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler()
    ch.setLevel(args.loglevel)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    file_util.create_dirname(args.output)
    if not(os.path.exists(args.output)):
        os.mkdir(args.output)

    if args.kommune == ['ALL']:
        nr2name, _ = kommunenummer()
        kommunenummer = map(to_kommunenr, nr2name.keys())
    else:
        kommunenummer = map(to_kommunenr, args.kommune)

    conversion = dict()
    if not(args.not_convert_tags):
        conversion = ssr2_tags.get_conversion(excel_filename = 'data/Tagging tabell SSR2.xlsx') # fixme: as argument
    
    for n in kommunenummer:
        print n
        filenames_to_clean = list()

        osm_filename = main(n, root=args.output, character_limit=args.character_limit,
                            create_multipoint_way=args.create_multipoint_way)
        #filenames.append(osm_filename)

        if not(args.not_convert_tags):
            osm_filename = ssr2_tags.replace_tags(osm_filename, conversion, exclude_empty=not(args.include_empty_tags))
            filenames_to_clean.append(osm_filename)
        else:
            filenames_to_clean.append(osm_filename)
        
        if not(args.not_split_hovedgruppe):
            split_filenames = ssr2_split.osm_split(osm_filename, split_key='ssr:hovedgruppe')
            filenames_to_clean.extend(split_filenames)

        if not(args.not_remove_extra_tags):
            tags_to_remove = ('ssr:hovedgruppe', 'ssr:gruppe', 'ssr:type',
                              'ssr:sorting', 'ssr:date')
            for f in filenames_to_clean:
                print 'cleaning', f
                content = file_util.read_file(f)
                osm = osmapis.OSM.from_xml(content)
                for item in osm:
                    for key in tags_to_remove:
                        item.tags.pop(key, '')
                osm.save(f)
