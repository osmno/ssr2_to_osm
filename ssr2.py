#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import re
import csv
import json
import glob
import warnings
import traceback
from multiprocessing import Pool
import signal
import time
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

def init_pool_worker():
    # https://stackoverflow.com/a/11312948
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def add_file_handler(filename='warnings.log'):
    fh = logging.FileHandler(filename, mode='w')
    fh.setLevel(logging.WARNING)
    #fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return fh

def parse_gml_point(point):
    with warnings.catch_warnings():
        warnings.simplefilter(action='ignore', category=FutureWarning)
        epsg = point['srsName']
        #print('epsg', epsg)
        projection = pyproj.Proj(init=epsg)#'epsg:%s' % srid)
        #print 'POINT', point
        utm33 = point.find('pos').text.split()
        lon, lat = projection(utm33[0], utm33[1], inverse=True)

        gml_id = point['gml:id']
    
    return lon, lat, gml_id

def parse_sortering(entry):
    """Extract sorterings-kode from xml tags app:sortering1kode and app:sortering2kode"""
    viktighet1 = entry.find('sortering1kode').text
    viktighet2 = entry.find('sortering2kode').text
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
    <sted>
      <stedsnavn> 
        <Stedsnavn> "NAME1" </stedsnavn>
      </stedsnavn>
      <stedsnavn> 
        <Stedsnavn> "NAME2" </stedsnavn>
      </stedsnavn>
    <sted>
    note the nested <stedsnavn><stedsnavn>...

    Returns a list of dictionaries for each name, where skrivemåte is 
    in return_only, default:
    ('godkjent', 'internasjonal', 'vedtatt', 'vedtattNavneledd')
    Items not in silently_ignore will be logged.
    """
    if additional_tags is None:
        additional_tags = dict()
    language_priority = entry.find('språkprioritering')
    
    if language_priority is None:
        language_priority = sorted(ssr_language_to_osm.keys())
        ix_no = language_priority.index('nor')
        # Put 'nor' first:
        del language_priority[ix_no]
        language_priority.insert(0, 'nor')
        language_priority = '-'.join(language_priority)
        logger.error('language priorty missing from file, inventing language_priority = %s',
                     language_priority)
    else:
        language_priority = language_priority.text

    additional_tags['name:language_priority'] = language_priority        

    parsed_names = list()
    for names in entry.find_all('stedsnavn', recursive=False):
        names_nested = names.find_all('Stedsnavn', recursive=False)
        assert len(names_nested) == 1, 'Vops: expected this to only be 1 element %s' % names
        names = names_nested[0]

        language = names.find(u'språk').text
        name_status = names.find('navnestatus').text
        name_status_num = name_status_to_num(name_status)
        #name_case_status = names.find('app:navnesakstatus') # seems to only be 'ubehandlet'
        eksonym = names.find('eksonym').text
        stedsnavnnummer = names.find('stedsnavnnummer').text
        if name_status_num in (4, 6):
            logger.error('Skipping name_status = "%s"', name_status)
            continue

        for skrivem in names.find_all(u'skrivemåte', recursive=False):
            skrivem_nested = skrivem.find_all(u'Skrivemåte', recursive=False)
            assert len(skrivem_nested) == 1, 'Vops: expected this to only be 1 element %s' % skrivem
            skrivem = skrivem_nested[0]
            
            #print 'SKRIVEM', skrivem.prettify()
            if additional_tags is None:
                tags = dict()
            else:
                tags = dict(additional_tags) # start with the additional tags

            # Date
            # Note: this date is potensially older than ssr:date, which covers the 'sted', this only covers the 'name'
            date = skrivem.find('oppdateringsdato').text
            try:
                date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f') # to python object
            except ValueError:
                date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S') # to python object

            date_str = date_python.strftime('%Y-%m-%d') # to string
                
            tags['name'] = skrivem.find('langnavn').text
            #print skrivem.prettify()
            tags['name:date'] = date_str
            tags['name:language'] = language
            tags['name:name_status'] = name_status
            tags['name:name_status_num'] = name_status_num
            tags['name:eksonym'] = eksonym
            tags['name:stedsnavnnummer'] = stedsnavnnummer
            #tags['name:order'] = skrivem.find('app:rekkef').text
            priority_spelling = skrivem.find(u'prioritertSkrivemåte').text # app:prioritertSkrivemåte
            if priority_spelling == u'true':
                priority_spelling = True
            elif priority_spelling == u'false':
                priority_spelling = False
            else:
                raise ValueError('Expected priority_spelling to to "true" or "false" not "%s"', priority_spelling)
            
            tags['name:priority_spelling'] = priority_spelling

            order_spelling = int(skrivem.find(u'skrivemåtenummer').text)
            tags['name:order_spelling'] = order_spelling

            status = skrivem.find(u'skrivemåtestatus').text
            tags['name:spelling_status'] = status
            
            if status in return_only:
                parsed_names.append((name_status_num, order_spelling, tags))
            else:
                if not(status in silently_ignore):
                    logger.info('ignoring non approved status = "%s" name = "%s"',
                                status, tags['name'])
            
    parsed_names_sort = sorted(parsed_names, key = lambda x: [x[0], x[1]])
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

ssr_language_to_osm = {'nor': 'no',
                       'smj': 'smj',
                       'sme': 'se',
                       'sma': 'sma',
                       'fkv': 'fkv',
                       'sms': 'sms',
                       'eng': 'en',
                       'rus': 'ru',
                       'swe': 'sv',
                       'dan': 'da',
                       'isl': 'is',
                       'kal': 'kl',
                       'fin': 'fi',
                       'deu': 'de'}
def ssr_language_to_osm_key(ssr_lang):
    try:
        return ssr_language_to_osm[ssr_lang]
    except KeyError:
        raise KeyError('lang key "%s" not found in conversion dict, add appropriate iso code: http://www.loc.gov/standards/iso639-2/php/code_list.php to conversion dictionary' % ssr_lang)

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

def sort_by_priority_spelling(names, language_priority):
    names = list(names)
    new_lst = list()
    for lang in language_priority.split('-'):
        lang_key = ssr_language_to_osm_key(lang)
        ix = 0
        while ix < len(names):
        #for l, item in names:
            l, item = names[ix]
            if l == lang_key:
                new_lst.append((l, item))
                del names[ix]
            else:
                ix += 1
                
    # Remaining:
    for l, item in names:
        logger.warning('language missing from language priority %s', l)
        new_lst.append((l, item))
    
    # assert len(names) == len(new_lst), 'names = %s != new_lst = %s' % (names, new_lst)
    # for item in names:
    #     assert item in new_lst
    return new_lst

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

def handle_multiple_priority_spellings(names_pri, languages=None, names=None):
    # get a unique and sorted list of languages to look at
    if languages is None:
        languages = list()
        for item in names_pri:
            lang = item['name:language']
            if lang not in languages:
                languages.append(lang)

    if names is None:
        names = list()
    
    for lang in languages:
        lang_key = ssr_language_to_osm_key(lang)
        # for ix, (l, _) in enumerate(names):
        #     if l == lang_key:
        #         current_lang = names[ix]
        #         break
        # else:
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
    osm_noName = osmapis.OSM()
    #multi_names = dict()
    #print soup.prettify()
    for entry in soup.find_all('Sted'):
        #print 'STED', entry.prettify()
        tags = dict()
        attribs = dict()
        stedsnr = entry.find('stedsnummer').text
        tags['ssr:stedsnr'] = stedsnr

        # Active?
        active = entry.find('stedstatus').text
        if active != 'aktiv':
            logger.info('ssr:stedsnr = %s not active = "%s". Skipping...', stedsnr, active)
            continue

        # Date
        date = entry.find('oppdateringsdato').text
        try:
            date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f') # to python object
        except ValueError:
            date_python = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S') # to python object

        date_str = date_python.strftime('%Y-%m-%d') # to string
        
        tags['ssr:hovedgruppe'] = entry.find('navneobjekthovedgruppe').text
        tags['ssr:gruppe'] = entry.find('navneobjektgruppe').text
        tags['ssr:type'] = entry.find('navneobjekttype').text
        tags['ssr:date'] = date_str

        # # Sorting:
        # sortering = parse_sortering(entry)
        # if sortering != '':
        #     tags['ssr:sorting'] = sortering

        # fixme: parse ssr:navnetype and ssr:navnekategori into proper openstreetmap tag(s)

        return_only = (u'godkjent', u'internasjonal', u'vedtatt', u'vedtattNavneledd', u'privat') # , u'uvurdert'
        parsed_names = parse_stedsnavn(entry, return_only=return_only,
                                       silently_ignore=[u'historisk', u'foreslått', 'uvurdert'])

        silently_ignore = list(return_only)
        silently_ignore.append(u'foreslått')
        silently_ignore.append(u'uvurdert')
        parsed_names_historic = parse_stedsnavn(entry, return_only=[u'historisk'],
                                                 silently_ignore=silently_ignore)
        silently_ignore = list(return_only)
        silently_ignore.append(u'historisk')
        silently_ignore.append(u'uvurdert')
        parsed_names_locale =    parse_stedsnavn(entry, return_only=[u'foreslått', 'uvurdert'],
                                                 silently_ignore=silently_ignore)

        language_priority = None
        if len(parsed_names) + len(parsed_names_historic) + len(parsed_names_locale) == 0:
            logger.warning('ssr:stedsnr = %s: No valid names found, skipping', stedsnr)
            continue
        else:
            # name:language_priority is equal for all elements in parsed_names
            # but we needs to skip through and find the first non-empty list:
            for lst in (parsed_names, parsed_names_historic, parsed_names_locale):
                try:
                    language_priority = lst[0]['name:language_priority'] # this is equal for all elements in parsed_names
                    break
                except:
                    pass
        
        languages = find_all_languages(parsed_names, parsed_names_historic, parsed_names_locale)
        languages = list(languages)
        if len(languages) != 1:
            logger.debug('ssr:stedsnr = %s, languages = %s', tags['ssr:stedsnr'], languages)
        # Convert to osm keys:
        lang_keys = list(map(ssr_language_to_osm_key, languages))

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

        # if tags['ssr:stedsnr'] == '321599':
        #     print 'languages', lang_keys
        #     print 'names', names
        #     print 'alt_names', alt_names_pri
        #     exit(1)

        for lang in languages:
            lang_key = ssr_language_to_osm_key(lang)
            lang_missing = True
            for l, lst in names:
                if l == lang_key:
                    lang_missing = False
                    break

            #if len(names) == 0:        # use alt_name instead if available
            if lang_missing and len(alt_names_pri) != 0:
                lang_names = handle_multiple_priority_spellings(alt_names_pri,
                                                                languages=[lang]) # only for lang
                assert len(lang_names) == 1
                names.append(lang_names[0])
                names = sort_by_priority_spelling(names, language_priority)

                # DEBUG:
                names_str = list()
                for lang, lst in names:
                    for item in lst:
                        names_str.append((lang, item['name']))

                logger.warning('ssr:stedsnr = %s: No priority spelling found for lang = %s, using alt_name to get "%s"',
                               tags['ssr:stedsnr'], lang, names_str)
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
                logger.info('ssr:stedsnr = %s: No name found',
                             tags['ssr:stedsnr'])
                #continue

        # # Create an alt_names_dct based on names_dct
        # alt_names_dct = defaultdict(list)
        # for key in names_dct:
        #     alt_key = key.replace('name', 'alt_name')
        #     for item in names_dct[key]:
        #         if not('added_to_name' in item and item['added_to_name']):
        #             alt_names_dct[alt_key].append(item)

        alt_names_dct = defaultdict(list)        
        if len(names) == 0:
            name_found = False
        else:
            name_found = True
            # 2.3) Add tags['name']
            # and tags['name:lang']
            names_str = list()
            for lang, lst in names:
                if len(lst) == 0:
                    continue
                
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
        # and no other :lang key is used for this place
        lang_suffix = ssr_language_to_osm.values()
        lang_suffic_without_no = list(lang_suffix)
        ix = lang_suffic_without_no.index('no')
        del lang_suffic_without_no[ix]
        lang_suffic_without_no = tuple(lang_suffic_without_no)

        multi_language = False
        if language_priority.startswith('nor'):
            for key in tags.keys():
                if key.endswith(lang_suffic_without_no):
                    multi_language = True
                    break

        if language_priority.startswith('nor') and not(multi_language):
            for key in list(tags.keys()):
                if key.endswith(':no'):
                    key_without_lang = key[:-len(':no')]
                    if key_without_lang in tags: # do not overwrite
                        # unless value is the same
                        if tags[key] != tags[key_without_lang]:
                            continue
                    
                    tags[key_without_lang] = tags[key]
                    del tags[key]

        # 5) Ensure we do not have alt_name:<lang> without a name:<lang>
        for key in list(tags.keys()):
            reg = re.match('alt_name:(\w+)', key)
            if reg:
                lang = reg.group(1)
                key_name = 'name:%s' % lang
                if key_name not in tags:
                    tags[key_name] = tags[key]
                    del tags[key]
                    if ';' in tags[key_name]:
                        logger.warning('empty name:%s, moving from alt_name:%s, FIXME: handle multiple names = %s',
                                       lang, lang, tags[key_name])
                        old_fixme = tags.pop('fixme', '')
                        fixme = 'multiple name:%s tags, choose one and add the other to alt_name:%s' % (lang, lang)
                        if old_fixme != '':
                            fixme = old_fixme + '; ' + fixme
                        
                        tags['fixme'] = fixme


        pos = entry.find('posisjon')
        positions = pos.find_all('Point')
        # print pos.prettify()
        # print positions
        # exit(1)
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

        if name_found:
            osm.add(osm_element)
        else:
            osm_noName.add(osm_element)

    return osm, osm_noName

class EmptyResultException(Exception):
    pass

def fetch_and_process_kommune(kommunenummer, xml_filename, osm_filename, osm_filename_noName,
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
        url = 'http://wfs.geonorge.no/skwms1/wfs.stedsnavn50?VERSION=2.0.0&SERVICE=WFS&srsName=EPSG:25832&REQUEST=GetFeature&TYPENAME=Sted&resultType=results&Filter=%3CFilter%3E%20%3CPropertyIsEqualTo%3E%20%3CValueReference%20xmlns:app=%22http://skjema.geonorge.no/SOSI/produktspesifikasjon/Stedsnavn/5.0%22%3Eapp:kommune/app:Kommune/app:kommunenummer%3C/ValueReference%3E%20%3CLiteral%3E{kommunenummer}%3C/Literal%3E%20%3C/PropertyIsEqualTo%3E%20%3C/Filter%3E"'
        #  --header "Content-Type:text/xml"'
        url = url.format(kommunenummer=kommunenummer)
    
    # get xml:
    req = gentle_requests.GentleRequests()
    d = req.get_cached(url, xml_filename)
    try:
        d = d.decode('utf-8')
    except: pass
    
    ensure_contains = '</wfs:FeatureCollection>'
    if ensure_contains not in d[-len(ensure_contains)-100:]:
        logger.error('ERROR, no ending in %s? Trying to re-download "%s"',
                     xml_filename, d[-len(ensure_contains)-100:-1])
        d = req.get_cached(url, xml_filename, old_age_days=0.1)

    if ensure_contains not in d[-len(ensure_contains)-100:]:
        raise Exception("Still no file ending for %s" % (xml_filename))
        
    if d is None:
        msg = 'Unable to fetch %s, cached to %s' % (url, xml_filename)
        logger.error(msg)
        raise EmptyResultException(msg)
    
    # parse xml:
    soup = BeautifulSoup(d[:character_limit], 'lxml-xml')
    osm, osm_noName = parse_geonorge(soup, create_multipoint_way=create_multipoint_way)
    # Save result:
    if len(osm) != 0:
        osm.save(osm_filename)
    else:
        #print(soup.prettify())
        raise EmptyResultException('Empty osm result for %s' % kommunenummer)

    if len(osm_noName) != 0:
        osm_noName.save(osm_filename_noName)
    
    return osm

def main(args, folder, n, conversion, url=None):
    print(n)
    start_time_kommune = datetime.datetime.now()
    
    for f in glob.glob(os.path.join(folder, '*.osm')):
        os.remove(f)

    xml_filename = os.path.join(folder, '%s-ssr.xml' % n)
    osm_filename = os.path.join(folder, '%s-ssr.osm' % n)
    osm_filename_noName = os.path.join(folder, '%s-ssr-NoName.osm' % n)
    log_filename = os.path.join(folder, '%s.log' % n)

    file_util.create_dirname(log_filename)
    logging_fh = add_file_handler(log_filename)

    output_clean_folder = os.path.join(folder, 'clean')
    if os.path.exists(output_clean_folder):
        shutil.rmtree(output_clean_folder)
    os.mkdir(output_clean_folder)

    # json_names_filename = os.path.join(folder, '%s-multi-names.json' % n)
    # csv_names_filename = os.path.join(folder, '%s-multi-names.csv' % n)

    # Go from %s-geonorge.xml to %s-all.osm
    try:
        fetch_and_process_kommune(n, xml_filename=xml_filename, url=url,
                                  osm_filename=osm_filename,
                                  osm_filename_noName=osm_filename_noName,
                                  character_limit=args.character_limit,
                                  create_multipoint_way=args.create_multipoint_way)
    except EmptyResultException as e:
        print('Empty result', e)
        return

    filenames_to_clean = list()
    # Go from %s-all.osm to %s-all-tagged.osm, removing %s-all.osm when done
    if not(args.not_convert_tags):
        for convert_filename in (osm_filename_noName, osm_filename):
            if os.path.exists(convert_filename):
                filename_base = convert_filename[:-len('.osm')]
                filename_out = "%s.osm" % filename_base.replace('-ssr', '') #'%s.osm' % (filename_base)
                filename_out_notTagged = '%s-%s.osm' % (filename_base.replace('-ssr', ''), 'NoTags')
                #filename_out_notTagged = filename_out_notTagged.replace('-all', '')
                
                ssr2_tags.replace_tags(convert_filename,
                                       filename_out, filename_out_notTagged,
                                       conversion, include_empty=args.include_empty_tags)
                # osm_filename should now be redundant, as all the information is in either filename_out or filename_out_notTagged
                # fixme: actually loop through and check this.
                if os.path.exists(filename_out) or os.path.exists(filename_out_notTagged):
                    os.remove(convert_filename)

        head, tail = os.path.split(filename_out)
        filename_out_cleaned = os.path.join(output_clean_folder, tail)
        shutil.copy(filename_out, filename_out_cleaned)
        filenames_to_clean.append(filename_out_cleaned)

    if not(args.not_split_hovedgruppe):
        split_filenames = ssr2_split.osm_split(filename_out_cleaned, split_key='ssr:hovedgruppe')
        filenames_to_clean.extend(split_filenames)

    # FIXME: function
    for filename in filenames_to_clean:
        content = file_util.read_file(filename)
        osm = osmapis.OSM.from_xml(content)
        tags_to_remove = ('ssr:hovedgruppe', 'ssr:gruppe', 'ssr:type', 'ssr:date')
        for item in osm:
            for key in tags_to_remove:
                item.tags.pop(key, '')
        osm.save(filename)
        #shutil.move(filename, output_clean_folder)

    end_time = datetime.datetime.now()
    #logger.info('Done: Kommune = %s, Duration: %s', n, end_time - start_time_kommune)
    print('Done: Kommune = %s, Duration: %s' % (n, end_time - start_time_kommune)) # reduce diff size of logs
        
    logger.removeHandler(logging_fh)

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
    parser.add_argument('--include_zz', default=False, action='store_true',
                        help='Do not download "land=zz", which contains nodes outside of mainland Norway')
    parser.add_argument('--parallel', default=0, type=int,
                        help='Process kommune list in parrallel using specified number of processes')

    start_time = datetime.datetime.now()
    
    args = parser.parse_args()

    root_logger = logger = logging.getLogger('utility_to_osm')
    root_logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler()
    ch.setLevel(args.loglevel)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    file_util.create_dirname(args.output)
    if not(os.path.exists(args.output)):
        os.mkdir(args.output)

    if args.kommune == ['ALL']:
        nr2name, _ = kommunenummer()
        kommunenummer = list(map(to_kommunenr, nr2name.keys()))
        kommunenummer.sort()
    else:
        kommunenummer = list(map(to_kommunenr, args.kommune))

    conversion = dict()
    if not(args.not_convert_tags):
        conversion = ssr2_tags.get_conversion(excel_filename = args.excel_tagging)

    #group_overview = defaultdict(list)
    root = args.output


    if args.include_zz:
        url = 'http://wfs.geonorge.no/skwms1/wfs.stedsnavn50?VERSION=2.0.0&SERVICE=WFS&srsName=EPSG:25832&REQUEST=GetFeature&TYPENAME=Sted&resultType=results&Filter=%3CFilter%3E%20%3CPropertyIsEqualTo%3E%20%3CValueReference%20xmlns:app=%22http://skjema.geonorge.no/SOSI/produktspesifikasjon/Stedsnavn/5.0%22%3Eapp:land/app:Land/app:landnummer%3C/ValueReference%3E%20%3CLiteral%3E{land}%3C/Literal%3E%20%3C/PropertyIsEqualTo%3E%20%3C/Filter%3E" --header "Content-Type:text/xml"'
        url = url.format(land='ZZ')

        n = 'ZZ'
        folder = os.path.join(root, n)
        main(args, folder, n, conversion, url=url)

    if args.parallel != 0:
        p = Pool(args.parallel, init_pool_worker)
    
    p_results = list()
    fatal_errors = list()
    for n in kommunenummer:
        folder = os.path.join(root, n)
        if args.parallel != 0:
            res = p.apply_async(main, (args, folder, n, conversion))
            p_results.append((n, res))
            #time.sleep(1) # to to be sligtly gentle to geonorge.no
        else:
            #main(args, folder, n, conversion)
            try:
                main(args, folder, n, conversion)
            except Exception as e:
                trace = traceback.format_exc()
                logger.error('Fatal error:%s %s', n, e)
                fatal_errors.append('ERROR: Komune %s failed with: %s.\n%s' % (n, e, trace))
        
        end_time = datetime.datetime.now()
        print('Elapsed time: {}'.format(end_time - start_time))

    # Wait for all pool results:
    for n, res in p_results:
        try:
            res.get()
        except Exception as e:
            trace = traceback.format_exc()
            logger.error('Fatal error:%s %s', n, e)
            fatal_errors.append('ERROR: Komune %s failed with: %s.\n%s' % (n, e, trace))
        

    for error in fatal_errors:
        print(error)
        
    # table = list()
    # for key in sorted(group_overview.keys()):
    #     row = list()
    #     row.extend(key.split(','))
    #     for item in group_overview[key]:
    #         row.append(str(item))
    #     table.append(row)

    # header = ['hovedgruppe', 'gruppe', 'type', 'freq ' + ', '.join(args.kommune),
    #           'tags']
    # for ix in range(len(header)):
    #     header[ix] = 'SSR2 ' + header[ix]
    
    # filename = os.path.join(args.output, 'group_overview.csv')
    # with open(filename, 'w', 'utf-8') as f:
    #     w = UnicodeWriter(f, dialect='excel', delimiter=';')
    #     w.writerow(header)
    #     w.writerows(table)
    
    end_time = datetime.datetime.now()
    print('Duration: {}'.format(end_time - start_time))
