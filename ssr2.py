#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import csv
import json
import glob
import shutil
import codecs
open = codecs.open
import datetime
from collections import defaultdict
import logging
logger = logging.getLogger('utility_to_osm.ssr2')

from bs4 import BeautifulSoup

# Shared helper function import:
import utility_to_osm
import utility_to_osm.overpass_helper as overpass_helper
import utility_to_osm.file_util as file_util
import utility_to_osm.gentle_requests as gentle_requests
import utility_to_osm.argparse_util as argparse_util
from utility_to_osm.kommunenummer import kommunenummer, to_kommunenr
from utility_to_osm.csv_unicode import UnicodeWriter

# third party:
from utility_to_osm import osmapis
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

name_status_conv = {'hovednavn': 1,
                    'sidenavn':  2,
                    'undernavn': 3,
                    'feilført' : 4,
                    'historisk': 5,
                    'avslåttnavnevalg': 6}

def name_status_to_num(name_status):
    key = name_status.lower()
    try:
        return name_status_conv[key]
    except KeyError:
        logger.error('invalid name_status = "%s"', name_status)
        return 10

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
        name_status_num = name_status_to_num(name_status)
        #name_case_status = names.find('app:navnesakstatus') # seems to only be 'ubehandlet'
        eksonym = names.find('app:eksonym').text
        stedsnavnnummer = names.find('app:stedsnavnnummer').text
        if name_status_num in (4, 6):
            logger.error('Skipping name_status = "%s"', name_status)
            continue
            
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

            # Date
            # Note: this date is potensially older than ssr:date, which covers the 'sted', this only covers the 'name'
            date = skrivem.find('app:oppdateringsdato').text
            try:
                date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f') # to python object
            except ValueError:
                date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S') # to python object

            date_str = date_python.strftime('%Y-%m-%d') # to string
                
            tags['name'] = skrivem.find('app:langnavn').text
            #print skrivem.prettify()
            tags['name:date'] = date_str
            tags['name:language'] = language
            tags['name:name_status'] = name_status
            tags['name:name_status_num'] = name_status_num
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

            order_spelling = int(skrivem.find('app:skrivem').text)
            tags['name:order_spelling'] = order_spelling

            # FIXME: BUG:
            #status = skrivem.find('app:skrivemåtestatus').text
            status = skrivem.find_all('app:skrivem')[1].text
            tags['name:spelling_status'] = status
            
            if status in return_only:
                parsed_names.append((name_status_num, order_spelling, tags))
            else:
                if not(status in silently_ignore):
                    logger.info('ignoring non approved status = "%s" name = "%s"',
                                status, tags['name'])
            
    parsed_names_sort = sorted(parsed_names)
    # if len(parsed_names_sort) >= 3:
    #     print parsed_names_sort
    #     exit(1)
    parsed_names_tags = list()
    for _, _, tags in parsed_names_sort:
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

def update_lang_name_dct(dct, parsed_names, tag_key, language, lang_key):
    """Updates the given dictionary dct with names in parsed_names that correspond to language, where
    the dictionary keys are:
        'name:lang1' = [list, of, names]
        'name:lang2' = [list, of, names]
    """
    # fixme: class?
    for name in parsed_names:
        if name['name:language'] == language:
            tag_key_lang = '%s:%s' % (tag_key, lang_key)
            dct[tag_key_lang].append(name) # ['name']

            name['added_to_lang_dct'] = True # debug only

def add_name_lang_tags(dct, tags):
    """Using dictionary 'dct' from above function, 
    add tags with comma seperated 'name' values to 'tags'"""
    # fixme: class
    for key in dct:
        lst = list()
        for item in dct[key]:
            lst.append(item['name'])

        assert key not in tags
        tags[key] = ';'.join(lst)
            
def sorted_priority_spelling(dct, language_priority, tag_key='name'):
    ''' Return, sorted by language_priority, a list of names where "name:priority_spelling" is True,
    where all elements have the same name_status
    '''
    # 1) Get the lowest name_status_num
    name_status_num_min = 6
    for key in dct:
        for item in dct[key]:
            name_status_num_min = min(name_status_num_min, item['name:name_status_num'])
    
    name_pri_spelling = list()
    for lang in language_priority.split('-'):
        lang_key = ssr_language_to_osm_key(lang)
        tag_key_lang = '%s:%s' % (tag_key, lang_key)
        parsed_names = dct[tag_key_lang]
        for item in parsed_names:
            if item['name:priority_spelling'] and name_status_num_min == item['name:name_status_num']:
                name_pri_spelling.append(item)#['name'])
    
    return name_pri_spelling

def sorted_remaining_spelling(dct, language_priority, tag_key='name'):
    ''' Return, sorted by language_priority, a list of names without a True "added_to_name"'''
    # fixme: shares a lot of code with above function
    # make the nested if statement a callback
    name_pri_spelling = list()
    for lang in language_priority.split('-'):
        lang_key = ssr_language_to_osm_key(lang)
        tag_key_lang = '%s:%s' % (tag_key, lang_key)
        parsed_names = dct[tag_key_lang]
        for item in parsed_names:
            if not('added_to_name' in item and item['added_to_name']):
                name_pri_spelling.append(item)#['name'])
    
    return name_pri_spelling

def handle_multiple_priority_spellings(names_pri):
    # get a unique and sorted list of languages to look at
    languages = list() 
    for item in names_pri:
        lang = item['name:language']
        if lang not in languages:
            languages.append(lang)

    names = []
    for lang in languages:
        lang_key = ssr_language_to_osm_key(lang)
        current_lang = (lang_key, []) # fixme: named tuple
        names.append(current_lang)
        for item in names_pri:
            # NOTE: not efficient, create a list in the previous loop instead
            if lang == item['name:language']:
                #item['added_to_name'] = True # Added later
                current_lang[1].append(item)

    return names

def parse_geonorge(soup, create_multipoint_way=False):
    # create OSM object:
    osm = osmapis.OSM()
    #multi_names = dict()
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

        # Date
        date = entry.find('app:oppdateringsdato').text
        try:
            date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f') # to python object
        except ValueError:
            date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S') # to python object

        date_str = date_python.strftime('%Y-%m-%d') # to string
        
        # tags['ssr:navnetype'] = entry.find('app:navneobjektgruppe').text
        # tags['ssr:navnekategori'] = entry.find('app:navneobjekthovedgruppe').text
        tags['ssr:hovedgruppe'] = entry.find('app:navneobjekthovedgruppe').text
        tags['ssr:gruppe'] = entry.find('app:navneobjektgruppe').text
        tags['ssr:type'] = entry.find('app:navneobjekttype').text
        tags['ssr:date'] = date_str

        # # Sorting:
        # sortering = parse_sortering(entry)
        # if sortering != '':
        #     tags['ssr:sorting'] = sortering

        # fixme: parse ssr:navnetype and ssr:navnekategori into proper openstreetmap tag(s)

        return_only = (u'godkjent', u'internasjonal', u'vedtatt', u'vedtattNavneledd', u'privat', u'uvurdert')
        parsed_names = parse_stedsnavn(entry, return_only=return_only,
                                       silently_ignore=[u'historisk', u'foreslått'])
        if len(parsed_names) == 0:
            logger.warning('ssr:stedsnr = %s: No valid names found, skipping', stedsnr)
            continue
        else:
            language_priority = parsed_names[0]['name:language_priority'] # this is equal for all elements in parsed_names

        silently_ignore = list(return_only)
        silently_ignore.append(u'foreslått')
        parsed_names_historic = parse_stedsnavn(entry, return_only=[u'historisk'],
                                                 silently_ignore=silently_ignore)
        silently_ignore = list(return_only)
        silently_ignore.append(u'historisk')
        parsed_names_locale =    parse_stedsnavn(entry, return_only=[u'foreslått'],
                                                 silently_ignore=silently_ignore)

        languages = find_all_languages(parsed_names, parsed_names_historic, parsed_names_locale)
        languages = list(languages)
        if len(languages) != 1:
            logger.debug('ssr:stedsnr = %s, languages = %s', tags['ssr:stedsnr'], languages)
        # Convert to osm keys:
        lang_keys = map(ssr_language_to_osm_key, languages)

        # Step 1) generate a dictionary, where keys are:
        # name:lang1 = [list, of, names]
        # name:lang2 = [list, of, names]
        # ...
        # Do the exact same operation on old_names and loc_names.
        names_dct = defaultdict(list)
        old_names_dct = defaultdict(list)
        loc_names_dct = defaultdict(list)
        for ix in range(len(languages)):
            update_lang_name_dct(names_dct, parsed_names, tag_key='name',
                                 language=languages[ix], lang_key=lang_keys[ix])
            update_lang_name_dct(old_names_dct, parsed_names_historic, tag_key='old_name',
                                 language=languages[ix], lang_key=lang_keys[ix])
            update_lang_name_dct(loc_names_dct, parsed_names_locale, tag_key='loc_name',
                                 language=languages[ix], lang_key=lang_keys[ix])

        # DEBUG prints:
        if len(names_dct) != 0:
            logger.debug('names_dct.keys = %s', names_dct.keys())
        if len(old_names_dct) != 0:
            logger.debug('old_names_dct.keys = %s', old_names_dct.keys())
        if len(loc_names_dct) != 0:
            logger.debug('loc_names_dct.keys = %s', loc_names_dct.keys())
        # END DEBUG
        
        # Step 2) Figure out name=*
        names = list()
        fixme = ''

        # 2.1 start with priority spelling
        names_pri = sorted_priority_spelling(names_dct, language_priority, tag_key='name')
        names = handle_multiple_priority_spellings(names_pri)

        # 2.2) Figure out alt_name
        alt_names_pri = sorted_remaining_spelling(names_dct, language_priority, tag_key='name')
        
        if len(names) == 0:        # use alt_name instead if available
            if len(alt_names_pri) != 0:
                names = handle_multiple_priority_spellings(alt_names_pri)

                # DEBUG:
                names_str = list()
                for lang, lst in names:
                    for item in lst:
                        names_str.append((lang, item['name']))
                
                logger.warning('ssr:stedsnr = %s: No priority spelling found, using alt_name to get "%s"',
                               tags['ssr:stedsnr'], names_str)
                # end DEBUG

            # # fixme: multi language support for this case?
            # if len(alt_names_pri) != 0:
            #     name = alt_names_pri[0]
            #     name['added_to_name'] = True
                
            #     names = [(ssr_language_to_osm_key(name['name:language']), [name])]

            #     alt_names_pri_names = [item['name'] for item in alt_names_pri]
            #     logger.warning('ssr:stedsnr = %s: No priority spelling found, using first alt_name = %d %s',
            #                    tags['ssr:stedsnr'], len(alt_names_pri_names), alt_names_pri_names)
            #     if len(alt_names_pri_names) >= 2:
            #         for ix in range(len(alt_names_pri)):
            #             logger.info('ssr:stedsnr = %s: alt_name[%d] = %s',
            #                         tags['ssr:stedsnr'],
            #                         ix, alt_names_pri[ix])
                
            #     del alt_names_pri[0]                
            else:
                logger.error('ssr:stedsnr = %s: No name found, skipping',
                             tags['ssr:stedsnr'])
                continue

        # # Create an alt_names_dct based on names_dct
        # alt_names_dct = defaultdict(list)
        # for key in names_dct:
        #     alt_key = key.replace('name', 'alt_name')
        #     for item in names_dct[key]:
        #         if not('added_to_name' in item and item['added_to_name']):
        #             alt_names_dct[alt_key].append(item)
            
        # 2.3) Add tags['name']
        # and tags['name:lang']
        assert len(names) != 0
        names_str = list()
        for lang, lst in names:
            names_str_lang = list() # one list for each language
            for item in lst:
                names_str_lang.append(item['name'])
                item['added_to_name'] = True

            s = ';'.join(names_str_lang)
            names_str.append(s)
            tags['name:%s' % lang] = s

            if len(names_str_lang) >= 2:
                logger.error('ssr:stedsnr = %s: Adding multiple names to name tag, this is not OK! name = "%s"',
                             tags['ssr:stedsnr'], s)
                fixme = 'multiple name tags, choose one and add the other to alt_name'

        assert len(names_str) != 0
        tags['name'] = ' - '.join(names_str)
        if fixme != '':
            tags['fixme'] = fixme
        
        if len(names_str) >= 2:
            logger.info('ssr:stedsnr = %s: Multi-language name tag = %s',
                        tags['ssr:stedsnr'], tags['name'])

        # Create alt_name again, now that we know 'added_to_name'
        # alt_names_pri = sorted_remaining_spelling(names_dct, language_priority, tag_key='name')
        alt_names_dct = defaultdict(list)
        for key in names_dct:
            alt_key = key.replace('name', 'alt_name')
            for item in names_dct[key]:
                if not('added_to_name' in item and item['added_to_name']):
                    alt_names_dct[alt_key].append(item)

        # 3) Add tags loc_name:lang, old_name:lang, alt_name:lang
        add_name_lang_tags(old_names_dct, tags)
        add_name_lang_tags(loc_names_dct, tags)
        add_name_lang_tags(alt_names_dct, tags)
        
        # 4) Remove redundant :lang keys for 'no' if priority language is 'no'
        if language_priority.startswith('nor'):
            for key in tags.keys():
                if key.endswith(':no'):
                    key_without_lang = key[:-len(':no')]
                    if key_without_lang in tags: # do not overwrite
                        # unless value is the same
                        if tags[key] != tags[key_without_lang]:
                            continue
                    
                    tags[key_without_lang] = tags[key]
                    del tags[key]
        
        #print names
        #exit(1)
        
        # if len(name_lang_lst) == 0:
        #     name_lang_lst = 

        #     name_str = ''
        #     if len(name_lang_lst != 0): # prefer to use name_lang_lst
        #         name_str = ' - '.join(name_lang_lst)
        #         if len(name_lang_lst) >= 2:
        #             logger.info('ssr:stedsnr = %s: multi-language name = "%s"',
        #                         name_tags['ssr:stedsnr'], name_str)
        #     else:               # simple case
        #         name_str = name['name']

        #     tags['name'] = name_str

        # 2.4) Add tags['name:lang']
        
            
        
        # # 2.4) Add tags['alt_name:lang']
        # if len(alt_names_pri) != 0:
        #     tags['alt_name'] = 
        
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

    return osm #, multi_names

def fetch_and_process_kommune(kommunenummer, xml_filename, osm_filename,
                              character_limit=-1, create_multipoint_way=False, url=None):
    if not(isinstance(kommunenummer, str)):
        raise ValueError('expected kommunenummer to be a string e.g. "0529"')

    # xml = file_util.read_file('ssr2_query_template.xml')
    # xml = xml.format(kommunenummer="0529")
    
    # url = 'http://wfs.geonorgen.no/skwms1/wfs.stedsnavn50'
    # d = req.post(url, data=xml,
    #              headers={'contentType':'text/xml; charset=UTF-8',
    #                       'dataType': 'text'})
    # print d.text
    # soup = BeautifulSoup(d.text, 'lxml')

    if url is None:
        url = 'http://wfs.geonorge.no/skwms1/wfs.stedsnavn50?VERSION=2.0.0&SERVICE=WFS&srsName=EPSG:25832&REQUEST=GetFeature&TYPENAME=Sted&resultType=results&Filter=%3CFilter%3E%20%3CPropertyIsEqualTo%3E%20%3CValueReference%20xmlns:app=%22http://skjema.geonorge.no/SOSI/produktspesifikasjon/Stedsnavn/5.0%22%3Eapp:kommune/app:Kommune/app:kommunenummer%3C/ValueReference%3E%20%3CLiteral%3E{kommunenummer}%3C/Literal%3E%20%3C/PropertyIsEqualTo%3E%20%3C/Filter%3E" --header "Content-Type:text/xml'
    url = url.format(kommunenummer=kommunenummer)

    # get xml:
    req = gentle_requests.GentleRequests()
    d = req.get_cached(url, xml_filename)
    # parse xml:
    soup = BeautifulSoup(d[:character_limit], 'lxml-xml')
    osm = parse_geonorge(soup, create_multipoint_way=create_multipoint_way)
    # Save result:
    if len(osm) != 0:
        osm.save(osm_filename)
    else:
        print(soup.prettify())
        raise Exception('Empty osm result')

    return osm

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='')
    argparse_util.add_verbosity(parser, default=logging.INFO)

    parser.add_argument('--output', default='output', 
                        help='Output root (working) directory. This tool will store files under <root>/<kommunenummer>/')
    parser.add_argument('--kommune', nargs='+', default=['ALL'], 
                        help='Specify one or more kommune (by kommune-number or kommune-name), or use the default "ALL" (slow!)')
    parser.add_argument('--excel_tagging', default='data/Tagging tabell SSR2.xlsx',
                        help='Specify excel conversion file, used to convert from ssr category to osm tags.')
    parser.add_argument('--character_limit', default=-1, type=int,
                        help='For quicker debugging, reduce the number of characters sent to the xml-parser, recommended --character_limit 100000 when playing around')
    parser.add_argument('--create_multipoint_way', default=False, action='store_true',
                        help='For debugging: create a osm-way for all elements that have multiple locations associated with it.')
    parser.add_argument('--not_split_hovedgruppe', default=False, action='store_true',
                        help='Do not create additional osm file copies, one for each "hovedgruppe"')
    parser.add_argument('--not_convert_tags', default=False, action='store_true',
                        help='Do not create additional osm file copies where ssr:hovedgruppe and ssr:type is used to translate to osm related tags')
    parser.add_argument('--include_empty_tags', default=False, action='store_true',
                        help='Do not remove nodes where no corresponding osm tags are found')

    start_time = datetime.datetime.now()
    
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
        conversion = ssr2_tags.get_conversion(excel_filename = args.excel_tagging)


    group_overview = defaultdict(list)
    root = args.output
    for n in kommunenummer:
        print n
        start_time_kommune = datetime.datetime.now()

        folder = os.path.join(root, n)
        for f in glob.glob(os.path.join(folder, '*.osm')):
            os.remove(f)

        xml_filename = os.path.join(folder, '%s-geonorge.xml' % n)
        osm_filename = os.path.join(folder, '%s-all.osm' % n)
        log_filename = os.path.join(folder, '%s.log' % n)
        # json_names_filename = os.path.join(folder, '%s-multi-names.json' % n)
        # csv_names_filename = os.path.join(folder, '%s-multi-names.csv' % n)

        file_util.create_dirname(log_filename)
        logging_fh = add_file_handler(log_filename)

        # Go from %s-geonorge.xml to %s-all.osm
        fetch_and_process_kommune(n, xml_filename=xml_filename,
                                  osm_filename=osm_filename,
                                  character_limit=args.character_limit,
                                  create_multipoint_way=args.create_multipoint_way)

        filenames_to_clean = list()
        # Go from %s-all.osm to %s-all-tagged.osm, removing %s-all.osm when done
        if not(args.not_convert_tags):
            filename_base = osm_filename[:-len('.osm')]
            filename_out = '%s-%s.osm' % (filename_base, 'tagged')
            filename_out_notTagged = '%s-%s.osm' % (filename_base, 'NotTagged')
            filename_out_notTagged = filename_out_notTagged.replace('-all', '')

            ssr2_tags.replace_tags(osm_filename,
                                   filename_out, filename_out_notTagged,
                                   conversion, include_empty=args.include_empty_tags,
                                   group_overview=group_overview)
            # osm_filename should now be redundant, as all the information is in either filename_out or filename_out_notTagged
            # fixme: actually loop through and check this.
            if os.path.exists(filename_out) or os.path.exists(filename_out_notTagged):
                os.remove(osm_filename)

            filename_out_cleaned = filename_out.replace('-all', '')
            shutil.copy(filename_out, filename_out_cleaned)
            filenames_to_clean.append(filename_out_cleaned)
            
        if not(args.not_split_hovedgruppe):
            split_filenames = ssr2_split.osm_split(filename_out_cleaned, split_key='ssr:hovedgruppe')
            filenames_to_clean.extend(split_filenames)

        # FIXME: function
        for filename in filenames_to_clean:
            content = file_util.read_file(filename)
            osm = osmapis.OSM.from_xml(content)
            tags_to_remove = ('ssr:hovedgruppe', 'ssr:gruppe', 'ssr:type')
            for item in osm:
                for key in tags_to_remove:
                    item.tags.pop(key, '')
            osm.save(filename)

        end_time = datetime.datetime.now()                
        logger.info('Done: Kommune = %s, Duration: %s', n, end_time - start_time_kommune)
        logger.removeHandler(logging_fh)
        print('Elapsed time: {}'.format(end_time - start_time))

    table = list()
    for key in sorted(group_overview.keys()):
        row = list()
        row.extend(key.split(','))
        for item in group_overview[key]:
            row.append(str(item))
        table.append(row)

    header = ['hovedgruppe', 'gruppe', 'type', 'freq ' + ', '.join(args.kommune),
              'tags']
    for ix in range(len(header)):
        header[ix] = 'SSR2 ' + header[ix]
    
    filename = os.path.join(args.output, 'group_overview.csv')
    with open(filename, 'w', 'utf-8') as f:
        w = UnicodeWriter(f, dialect='excel', delimiter=';')
        w.writerow(header)
        w.writerows(table)
    
    end_time = datetime.datetime.now()
    print('Duration: {}'.format(end_time - start_time))
