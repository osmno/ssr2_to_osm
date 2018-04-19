import os
import re
import logging
logger = logging.getLogger('utility_to_osm.ssr2.generate_webpage')

import utility_to_osm.argparse_util as argparse_util
from utility_to_osm.kommunenummer import kommunenummer, kommune_fylke
import utility_to_osm.file_util as file_util
from utility_to_osm.file_util import open_utf8
from utility_to_osm import osmapis

from jinja2 import Template
import humanize

link_template = u'<a href="{href}"\ntitle="{title}">{text}</a>'


footer = """
<!-- FOOTER  -->
<div id="footer_wrap" class="outer">
  <footer class="inner">
    <p class="copyright">This page is maintained by <a href="https://github.com/obtitus">obtitus</a></p>
    <p class="copyright">Map data &copy;<a href="http://openstreetmap.org">OpenStreetMap</a> contributors,
      <a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a></p>
    <p class="copyright">&copy;<a href="https://data.norge.no/nlod/no/1.0">NLOD</a></p>
  </footer>
</div>
"""

header = """
<!-- HEADER -->
<div id="header_wrap" class="outer">
  <header class="inner">
    <a id="forkme_banner" href="https://github.com/obtitus/ssr2_to_osm">View on GitHub</a>
    <h1 id="project_title">SSR2 import to OpenStreetMap.org</h1>
    <h2 id="project_tagline">Data files for importing Norwegian placenames from Kartverket, ssr2, into OpenStreetMap</h2>
  </header>
</div>
"""

def create_text(filename, f):
    if f.endswith('.osm'):
        if re.match('\d\d\d\d-', f):
            f = f[5:]
            f = f.replace('-', ' ')
            f = f.replace('tagged', '')
            f = f.replace(' .osm', '.osm')
            f = f.strip()
            if f == '.osm':
                f = 'all.osm'

            content = file_util.read_file(filename)
            osm = osmapis.OSM.from_xml(content)
            N_nodes = len(osm)
            N_nodes_str = '%s node' % N_nodes
            if N_nodes > 1:
                N_nodes_str += 's'

            # N_bytes = os.path.getsize(filename)
            # N_bytes_str = humanize.naturalsize(N_bytes, format='%d')
            
            f = '%s (%s)' % (f, N_nodes_str)
    else:
        pass
    return f

def write_template(template_input, template_output, **template_kwargs):
    with open_utf8(template_input) as f:
        template = Template(f.read())

    template_kwargs['header'] = template_kwargs.pop('header', header)
    template_kwargs['footer'] = template_kwargs.pop('footer', footer)
    page = template.render(**template_kwargs)

    with open_utf8(template_output, 'w') as output:
        output.write(page)

def create_main_table(data_dir='output', cache_dir='data'):
    table = list()
    kommune_nr2name, kommune_name2nr = kommunenummer(cache_dir=cache_dir)
    fylke_nr2name = kommune_fylke(cache_dir=cache_dir)
    
    for kommune_nr in os.listdir(data_dir):
        folder = os.path.join(data_dir, kommune_nr)
        if os.path.isdir(folder):
            try:
                kommune_name = kommune_nr2name[int(kommune_nr)] + ' kommune'
            except KeyError as e:
                logger.warning('Could not translate kommune_nr = %s to a name. Skipping', kommune_nr)
                #kommune_name = 'ukjent'
                continue
            except ValueError as e:
                if kommune_nr == 'ZZ':
                    kommune_name = 'Outside mainland'
                else:
                    raise ValueError(e)

            try:
                fylke_name = fylke_nr2name[int(kommune_nr)] + ' fylke'
            except KeyError as e:
                logger.warning('Could not translate kommune_nr = %s to a fylke-name. Skipping', kommune_nr)
                #fylke_name = 'ukjent'
                continue
            except ValueError:
                if kommune_nr == 'ZZ':
                    fylke_name = ''
                else:
                    raise ValueError(e)
            

            row = list()
            dataset_for_import = [] # expecting a single entry here
            excluded_from_import = []
            excerpts_for_import = []
            raw_data = []
            log = []
            for root, dirs, files in os.walk(folder):
                for f in files:
                    f = f.decode('utf8')
                    if f.endswith(('.osm', '.xml', '.log')):
                        filename = os.path.join(root, f)
                        text = create_text(filename, f)
                        href = filename.replace('html/', '')
                        url = link_template.format(href=href,
                                                   title=filename,
                                                   text=text)
                        if root.endswith('clean'):
                            excerpts_for_import.append(url)
                        elif f.endswith('all-tagged.osm'):
                            dataset_for_import.append(url)
                        elif 'noName' in f or 'notTagged' in f:
                            excluded_from_import.append(url)
                        elif f.endswith('.xml'):
                            raw_data.append(url)
                        elif f.endswith('.log'):
                            log.append(url)
                        else:
                            pass # ignore

            row.append("%s" % fylke_name)
            log.insert(0, "%s %s" % (kommune_nr, kommune_name))
            row.append(log)
            row.append(dataset_for_import)
            row.append(excerpts_for_import)            
            row.append(excluded_from_import)
            row.append(raw_data)

            table.append(row)

    return table

def main(data_dir='html/data/', root_output='html', template='html/template.html'):
    output_filename = os.path.join(root_output, 'index.html')
    
    table = create_main_table(data_dir, cache_dir=data_dir)
    write_template(template, output_filename, table=table, info='')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='')
    argparse_util.add_verbosity(parser, default=logging.INFO)
    
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)

    main()
