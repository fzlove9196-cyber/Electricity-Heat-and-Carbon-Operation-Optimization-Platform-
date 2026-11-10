import os, tempfile
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="simagent_data_"))
os.environ.setdefault("ARTIFACT_DIR", tempfile.mkdtemp(prefix="simagent_art_"))
os.environ["LLM_MOCK"] = "1"
os.environ.setdefault("KNOWLEDGE_SEED", "0")
