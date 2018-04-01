kommuner = 2111 0941 1850 2011 5043 0213 0529 0904 1253 5001 0301 2020 1002 0710 1902 2030 2012

all: normal debug_way 

normal:
	python ssr2.py --output output/ --kommune $(kommuner)

debug_way:
	python ssr2.py --output output_multi_point_as_way/ --create_multipoint_way --include_empty_tags --kommune $(kommuner)
