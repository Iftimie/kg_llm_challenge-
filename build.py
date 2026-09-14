"""Build KG from CSVs with Morph-KGC. Run: python build.py"""
import csv
import morph_kgc
from rdflib import Graph, Namespace

CRM = Namespace("https://example.org/sales-kg/")
RES = Namespace("https://example.org/sales-kg/resource/")

# 1. Materialize RML -> kg.nt
g = morph_kgc.materialize("morph.ini")
g.serialize("kg.nt", format="ntriples")
print(f"materialized: {len(g)} triples")

# 2. Small enrichment RML can't do on CSVs: decisionMakerFor.
# contacts.csv has no deal_id, so link decision makers to all deals of same account.
deal_by_account: dict[str, list[str]] = {}
with open("mock_crm_dataset/deals.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        deal_by_account.setdefault(row["account_id"], []).append(row["deal_id"])

with open("mock_crm_dataset/contacts.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["is_decision_maker"].strip().lower() == "true":
            for deal_id in deal_by_account.get(row["account_id"], []):
                g.add((RES[f"Contact_{row['contact_id']}"], CRM.decisionMakerFor, RES[f"Deal_{deal_id}"]))

g.serialize("kg.nt", format="ntriples")
print(f"final: {len(g)} triples -> kg.nt")

# 3. SHACL validation (shapes.ttl)
from pyshacl import validate
sh = Graph()
sh.parse("shapes.ttl", format="turtle")
conforms, _, report = validate(g, shacl_graph=sh)
print(report.strip().splitlines()[0] if report else conforms)
if not conforms:
    print(report)
    raise SystemExit("SHACL validation FAILED")
print("SHACL validation passed")

# 3. Quick sanity counts
from rdflib.namespace import RDF
for cls in ["Account", "CustomerContact", "Deal", "Interaction", "Transcript", "Product", "SalesRep", "Industry"]:
    print(cls, len(list(g.triples((None, RDF.type, CRM[cls])))))
