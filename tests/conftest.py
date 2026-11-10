import os, tempfile
# Tests must not inherit a developer's or clean-room server's DATA_DIR /
# KNOWLEDGE_SEED (setdefault would keep those and pollute or fail assertions).
# Opt in to a shared directory only with SIMAGENT_TEST_SHARED_DATA=1.
os.environ["LLM_MOCK"] = "1"
os.environ["KNOWLEDGE_SEED"] = "0"
os.environ["RAG_PRELOAD"] = "0"
if os.getenv("SIMAGENT_TEST_SHARED_DATA") != "1":
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="simagent_data_")
    os.environ["ARTIFACT_DIR"] = tempfile.mkdtemp(prefix="simagent_art_")
