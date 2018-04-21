from flask import Flask
app = Flask('ssr2_to_osm_flask')

@app.route("/")
def hello():
    return "Hello World!"
