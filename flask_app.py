#!/usr/bin/env python
from flask import Flask
app = Flask('ssr2_to_osm_flask')

@app.route("/")
def hello():
    return "Hello World!"

if __name__ == '__main__':
    app.run(debug=True,
            host='0.0.0.0')
