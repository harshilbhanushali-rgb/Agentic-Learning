import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


@dataclass(frozen=True)
class Config:
    gemma_api_key: str
    database_url: str
    joveo_speakers_lower: frozenset
    naren_name_lower: str
    pinecone_api_key: str
    pinecone_index_name: str
    gemma_api_keys: tuple = ()


def load_config() -> Config:
    api_key = os.environ["GEMMA_API_KEY"]
    db_url = os.environ["DATABASE_URL"]
    joveo_raw = os.environ["JOVEO_SPEAKER_NAMES"]
    naren_raw = os.environ["NAREN_SPEAKER_NAME"]
    joveo_lower = frozenset(n.strip().lower() for n in joveo_raw.split(",") if n.strip())
    extra_key = os.environ.get("GEMMA_API_KEY_2", "").strip()
    gemma_api_keys = (api_key, extra_key) if extra_key else (api_key,)
    return Config(
        gemma_api_key=api_key,
        database_url=db_url,
        joveo_speakers_lower=joveo_lower,
        naren_name_lower=naren_raw.strip().lower(),
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        pinecone_index_name=os.environ["PINECONE_INDEX_NAME"],
        gemma_api_keys=gemma_api_keys,
    )
