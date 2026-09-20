import asyncio
import logging
import sys
import os

# Add zenaipex to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from zenaipex.services.knowledge_service import extract_text
from zenaipex.ai.semantic_chunker import SemanticChunker
from zenaipex.ai.chunk_validator import CoverageValidator
from zenaipex.ai.vector_store import NamespacedVectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main(txt_path: str, namespace: str):
    logger.info(f"Reading text from {txt_path}...")
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Read failed: {e}")
        return
        
    logger.info(f"Extracted {len(content)} characters. Running SemanticChunker...")
    
    chunker = SemanticChunker(max_chunk_size=1500)
    chunk_dicts = chunker.chunk(content)
    logger.info(f"Generated {len(chunk_dicts)} chunks.")
    
    logger.info("Running CoverageValidator (Bypassed for sales text)")
    
    # Modules stats
    modules = {}
    for c in chunk_dicts:
        m = c["metadata"].get("module_number", "") + " " + c["metadata"].get("module_name", "")
        modules[m.strip()] = modules.get(m.strip(), 0) + 1
        
    logger.info(f"Modules Detected: {len(modules)}")
    for m, count in modules.items():
        logger.info(f"  - {m}: {count} chunks")
        
    logger.info(f"Initializing Pinecone NamespacedVectorStore for namespace: {namespace}")
    vs = NamespacedVectorStore(namespace=namespace)
    
    chunks_text = [c["text"] for c in chunk_dicts]
    
    logger.info("Generating embeddings...")
    embeddings = vs.generate_embeddings(chunks_text)
    
    logger.info("Upserting vectors into Pinecone...")
    vectors = []
    for i, (c, e) in enumerate(zip(chunk_dicts, embeddings)):
        v_id = f"sales_chunk_{i}"
        
        # Pinecone requires metadata to be dict of string, number, boolean, or list of strings
        # Make sure our metadata doesn't contain nulls or unsupported types
        clean_meta = {}
        for k, v in c["metadata"].items():
            if v is not None:
                clean_meta[k] = v
                
        # Also need to add text for RAG retrieval
        clean_meta["text"] = c["text"]
        
        vectors.append({
            "id": v_id,
            "values": e,
            "metadata": clean_meta
        })
        
    await vs.upsert_vectors(vectors=vectors)
        
    logger.info(f"Successfully ingested {len(vectors)} chunks into Pinecone namespace '{namespace}'.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(main(sys.argv[1], "603d2b5b9f1b2c3d4e5f6a7b"))
    else:
        print("Usage: python ingest_sales.py <path_to_txt>")
