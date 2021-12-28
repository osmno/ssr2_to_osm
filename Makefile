python=. venv/bin/activate; python
git=/usr/bin/git

kommuner = 3020
#1101 3020 

#
all:
	$(python) ssr2.py --output ssr2_to_osm_data/data/ --kommune ALL --include_zz --parallel 10 -q
	$(MAKE) webpage
#	$(MAKE) sync
#	$(MAKE) rotate_logs

#--include_zz
debug:
	$(python) ssr2.py --output ssr2_to_osm_data/data/ --kommune $(kommuner) 
#$(MAKE) webpage

webpage:
	$(python) generate_webpage.py

debug_way:
	($python) ssr2.py --output output_multi_point_as_way/ --create_multipoint_way --include_empty_tags --kommune $(kommuner)
	rsync -rt --delete output_multi_point_as_way/ /Users/ob/Google\ Drive/ssr2_to_osm_data/output_multi_point_as_way/

sync:
	-cd ssr2_to_osm_data;$(git) add -A;
	-cd ssr2_to_osm_data;$(git) com -am "Data update";
	-cd ssr2_to_osm_data;$(git) push;

#sync:
#	s3cmd sync -H --delete-removed --acl-public --storage-class=REDUCED_REDUNDANCY --exclude=*DS_Store ssr2_to_osm/ s3://ssr2-to-osm/
#	s3cmd setacl s3://ssr2-to-osm/ --acl-public --recursive
#	rsync -rt --delete html/data/ /Users/ob/Google\ Drive/ssr2_to_osm_data/output/

rotate_logs:
	logrotate logrotate.conf --state=logrotate.state
