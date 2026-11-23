import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
CASES = DATA / "cases"
SOURCES = DATA / "sources"
KNOWLEDGE = DATA / "knowledge"
WEB = ROOT / "web"
for p in (CASES, SOURCES, KNOWLEDGE):
    p.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
# Vision/structuring model (non-reasoning = fast) and search model.
EXTRACT_MODEL = os.getenv("HV_EXTRACT_MODEL", "gpt-5.4-mini")
SEARCH_MODEL = os.getenv("HV_SEARCH_MODEL", "gpt-5.4-mini")
USE_LLM = bool(OPENAI_API_KEY) and os.getenv("HV_DISABLE_LLM", "") != "1"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

UGC_TYPES = {  # unitypeID -> (label, public page token)
    1: ("Central University", "ddmCMsxJZgXH2S/m0uMOKQ=="),
    2: ("State University", "LZ1FUMk6U2JWGNLvhWfVSA=="),
    3: ("State Private University", "0wBmFB1Rb4JGVzq9UP/iOg=="),
    4: ("Deemed to be University", "UCL6fMspL2LJS89kv++N3A=="),
}
UGC_PAGE = "https://www.ugc.gov.in/universitydetails/university?type={token}"
UGC_API = "https://www.ugc.gov.in/universitydetails/Getuniversity_details?unitypeID={t}"
AICTE_LIST = "https://aicte.gov.in/sites/default/files/approval/2025-26/Groupwise-List%20of%20Institutions_compressed.pdf"
AICTE_NOTICE = "https://www.aicte.gov.in/sites/default/files/approval/2025-26/Public%20Notice%202025-26.pdf"
AICTE_YEAR = "2026"  # approval session 2025-26
SOURCE_MAX_AGE_DAYS = 7
