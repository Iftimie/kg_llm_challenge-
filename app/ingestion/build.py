"""Build KG from CSVs with Morph-KGC. Run: python build.py"""
import csv
import os
import pathlib
import tempfile

import morph_kgc
from rdflib import Graph, Namespace

CRM = Namespace("https://example.org/sales-kg/")
RES = Namespace("https://example.org/sales-kg/resource/")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _materialize(data_dir: pathlib.Path) -> Graph:
    """Materialize mappings.ttl (repo root) with sources pointing at data_dir (absolute paths)."""
    mappings_src = (REPO_ROOT / "ontology" / "mappings.ttl").read_text(encoding="utf-8")
    replaced = mappings_src.replace("mock_crm_dataset/", data_dir.as_posix() + "/")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        tmp_mappings = tmp_path / "mappings.ttl"
        tmp_ini = tmp_path / "morph.ini"
        tmp_mappings.write_text(replaced, encoding="utf-8")
        tmp_ini.write_text(
            f"[CONFIGURATION]\noutput_format = N-TRIPLES\n\n[DataSource]\nmappings = {tmp_mappings.as_posix()}\n",
            encoding="utf-8",
        )
        g = morph_kgc.materialize(str(tmp_ini))
    return g


def build(data_dir: pathlib.Path | None = None) -> tuple[int, str]:
    """Build the KG from CSVs, enrich, validate with SHACL, serialize to ``kg.nt``.

    The output path defaults to ``REPO_ROOT/kg.nt`` but can be overridden with the
    ``KG_NT`` environment variable. Returns ``(triple_count, data_dir_as_str)``.
    """
    if data_dir is None:
        data_dir = pathlib.Path(
            os.environ.get("DATA_DIR", str(REPO_ROOT / "datasets" / "first_ingestion"))
        )
    data_dir = pathlib.Path(data_dir)

    # 1. Materialize RML -> Graph
    g = _materialize(data_dir)
    print(f"materialized: {len(g)} triples")

    # 2. Small enrichment RML can't do on CSVs: decisionMakerFor.
    # contacts.csv has no deal_id, so link decision makers to all deals of same account.
    deal_by_account: dict[str, list[str]] = {}
    with open(data_dir / "deals.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            deal_by_account.setdefault(row["account_id"], []).append(row["deal_id"])

    with open(data_dir / "contacts.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["is_decision_maker"].strip().lower() == "true":
                for deal_id in deal_by_account.get(row["account_id"], []):
                    g.add((RES[f"Contact_{row['contact_id']}"], CRM.decisionMakerFor, RES[f"Deal_{deal_id}"]))

    kg_nt = pathlib.Path(os.environ.get("KG_NT", str(REPO_ROOT / "kg.nt")))
    g.serialize(kg_nt, format="ntriples")
    print(f"final: {len(g)} triples -> {kg_nt}")

    # 3. SHACL validation (shapes.ttl)
    from pyshacl import validate
    sh = Graph()
    sh.parse(REPO_ROOT / "ontology" / "shapes.ttl", format="turtle")
    conforms, _, report = validate(g, shacl_graph=sh)
    print(report.strip().splitlines()[0] if report else conforms)
    if not conforms:
        print(report)
        raise SystemExit("SHACL validation FAILED")
    print("SHACL validation passed")

    # 4. Quick sanity counts
    from rdflib.namespace import RDF
    for cls in ["Account", "CustomerContact", "Deal", "Interaction", "Transcript", "Product", "SalesRep", "Industry"]:
        print(cls, len(list(g.triples((None, RDF.type, CRM[cls])))))

    return (len(g), str(data_dir))


def main():
    build()


if __name__ == "__main__":
    main()
