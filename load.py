"""Load ontology + kg.nt + extracted/*.ttl into local GraphDB. Run: docker compose up -d, then python load.py"""
import glob
import os

import requests

GRAPHDB = "http://localhost:7200"
REPO = "sales-kg"

# 1. Create repo if missing (minimal free-text config)
s = requests.get(f"{GRAPHDB}/rest/repositories").json()
if not any(r["id"] == REPO for r in s):
    config = f"""@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rep: <http://www.openrdf.org/config/repository#> .
@prefix sr: <http://www.openrdf.org/config/repository/sail#> .
@prefix sail: <http://www.openrdf.org/config/sail#> .
[] a rep:Repository ; rep:repositoryID "{REPO}" ; rdfs:label "{REPO}" ;
   rep:repositoryImpl [ rep:repositoryType "graphdb:SailRepository" ;
     sr:sailImpl [ sail:sailType "graphdb:Sail" ] ] ."""
    requests.post(f"{GRAPHDB}/rest/repositories",
                  files={"config": ("repo.ttl", config)}).raise_for_status()
    print("repo created")
else:
    print("repo exists")

# 2. Upload files into separate contexts
for path, ctx in [("sales_kg_ontology_v1.ttl", "http://example.org/sales-kg/graph/ontology"),
                  ("kg.nt", "http://example.org/sales-kg/graph/crm")]:
    with open(path, "rb") as f:
        r = requests.put(f"{GRAPHDB}/repositories/{REPO}/statements",
                         params={"context": f"<{ctx}>"},
                         headers={"Content-Type": "application/n-triples" if path.endswith(".nt") else "application/x-turtle"},
                         data=f)
        r.raise_for_status()
        print("loaded", path, r.status_code)

# 3. Extracted transcript facts -> one shared named graph (append)
if os.path.isdir("extracted"):
    for path in sorted(glob.glob(os.path.join("extracted", "T*.ttl"))):
        with open(path, "rb") as f:
            r = requests.put(f"{GRAPHDB}/repositories/{REPO}/statements",
                             params={"context": "<https://example.org/sales-kg/graph/extracted>"},
                             headers={"Content-Type": "text/turtle"},
                             data=f)
            r.raise_for_status()
            print("loaded", path, r.status_code)

# 4. Sanity check
q = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
r = requests.get(f"{GRAPHDB}/repositories/{REPO}", params={"query": q},
                 headers={"Accept": "application/sparql-results+json"})
print("total triples:", r.json()["results"]["bindings"][0]["n"]["value"])
