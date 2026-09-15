"""Load ontology + kg.nt + extracted/*.ttl into local GraphDB. Run: docker compose up -d, then python load.py"""
import glob
import os
import pathlib

import requests

REPO_ROOT = pathlib.Path(__file__).parent


def load(kg_nt=None, ontology=None, extracted_dir=None) -> dict:
    """Create the GraphDB repo (if missing) and upload ontology, kg.nt, and extracted T*.ttl files.

    Loading is idempotent: each target named graph is cleared immediately before
    its upload, so a reload replaces the previous content and the KG mirrors the
    currently ingested data dir instead of accumulating stale triples.

    Returns a summary dict: {repo, total_triples, loaded}.
    """
    kg_nt = pathlib.Path(kg_nt) if kg_nt is not None else REPO_ROOT / "kg.nt"
    ontology = pathlib.Path(ontology) if ontology is not None else REPO_ROOT / "sales_kg_ontology_v1_llm_friendly.ttl"
    data_dir = pathlib.Path(os.environ.get("DATA_DIR", str(REPO_ROOT / "mock_crm_dataset")))
    extracted_dir = pathlib.Path(extracted_dir) if extracted_dir is not None else data_dir / "extracted"

    GRAPHDB = os.environ.get("GRAPHDB_URL", "http://127.0.0.1:7200")
    REPO = os.environ.get("GRAPHDB_REPO", "sales-kg")

    loaded = []

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

    # 2. Upload files into separate contexts, clearing each target graph first so
    #    a reload replaces rather than appends.
    for path, ctx in [(ontology, "http://example.org/sales-kg/graph/ontology"),
                      (kg_nt, "http://example.org/sales-kg/graph/crm")]:
        requests.delete(
            f"{GRAPHDB}/repositories/{REPO}/statements",
            params={"context": f"<{ctx}>"},
        ).raise_for_status()
        with open(path, "rb") as f:
            r = requests.post(f"{GRAPHDB}/repositories/{REPO}/statements",
                             params={"context": f"<{ctx}>"},
                             headers={"Content-Type": "application/n-triples" if str(path).endswith(".nt") else "application/x-turtle"},
                             data=f)
            r.raise_for_status()
            print("loaded", path, r.status_code)
            loaded.append(path.name)

    # 3. Extracted transcript facts -> one shared named graph. The shared context
    #    is cleared once before the loop so the reload mirrors extracted/*.ttl.
    if extracted_dir.is_dir():
        extracted_ctx = "https://example.org/sales-kg/graph/extracted"
        requests.delete(
            f"{GRAPHDB}/repositories/{REPO}/statements",
            params={"context": f"<{extracted_ctx}>"},
        ).raise_for_status()
        for path in sorted(extracted_dir.glob("T*.ttl")):
            with open(path, "rb") as f:
                r = requests.post(f"{GRAPHDB}/repositories/{REPO}/statements",
                                 params={"context": f"<{extracted_ctx}>"},
                                 headers={"Content-Type": "text/turtle"},
                                 data=f)
                r.raise_for_status()
                print("loaded", path, r.status_code)
                loaded.append(path.name)

    # 4. Sanity check
    q = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
    r = requests.get(f"{GRAPHDB}/repositories/{REPO}", params={"query": q},
                     headers={"Accept": "application/sparql-results+json"})
    total_triples = r.json()["results"]["bindings"][0]["n"]["value"]
    print("total triples:", total_triples)

    return {"repo": REPO, "total_triples": int(total_triples), "loaded": loaded}


def main() -> None:
    load()


if __name__ == "__main__":
    main()
