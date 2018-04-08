kommuner = 2111 0941 1850 2011 5043 0213 0529 0904 1253 5001 0301 2020 1002 0710 1902 2030 2012 1201 1103 0106 0501 0806

all: normal debug_way 

normal:
	python ssr2.py --output html/data/ --kommune $(kommuner)
	python generate_webpage
	s3cmd sync -H --skip-existing --delete-removed --acl-public --storage-class=REDUCED_REDUNDANCY --exclude=*DS_Store html/ s3://ssr2-to-osm/
	s3cmd setacl s3://ssr2-to-osm/ --acl-public --recursive
	rsync -rt --delete html/data/ /Users/ob/Google\ Drive/ssr2_to_osm_data/output/

debug_way:
	python ssr2.py --output output_multi_point_as_way/ --create_multipoint_way --include_empty_tags --kommune $(kommuner)
	rsync -rt --delete output_multi_point_as_way/ /Users/ob/Google\ Drive/ssr2_to_osm_data/output_multi_point_as_way/
