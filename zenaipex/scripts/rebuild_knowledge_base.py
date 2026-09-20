import asyncio
import logging
from bson import ObjectId

# Setup environment for standalone script
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.database import col_documents, col_knowledge_bases, connect_db
from services import knowledge_service
from core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    await connect_db()
    logger.info("Starting Comprehensive Knowledge Base Rebuild")
    
    docs = await col_documents().find({}).to_list(length=1000)
    logger.info(f"Found {len(docs)} documents to rebuild.")
    
    report_lines = []
    report_lines.append("="*80)
    report_lines.append(f"{'Company ID':<26} | {'Document':<30} | {'Old Chunks':<12} | {'New Chunks':<12} | {'Status'}")
    report_lines.append("-" * 80)
    
    for doc in docs:
        doc_id = str(doc["_id"])
        company_id = doc["company_id"]
        filename = doc["filename"]
        old_chunk_count = doc.get("chunk_count", 0)
        
        logger.info(f"Reprocessing {filename} ({doc_id}) for company {company_id}...")
        
        try:
            # We call the internal task directly to wait for it instead of create_task
            kb = await knowledge_service.get_knowledge_base(company_id, doc["knowledge_base_id"])
            if not kb:
                raise ValueError("Knowledge base not found")
                
            storage_path = doc.get("storage_path")
            content_type = doc.get("content_type", "text/plain")
            
            # Clean old vectors
            old_vector_ids = doc.get("vector_ids", [])
            if old_vector_ids:
                from ai.vector_store import NamespacedVectorStore
                vs = NamespacedVectorStore(namespace=kb["pinecone_namespace"])
                try:
                    await vs.delete_vectors(old_vector_ids)
                    logger.info(f"Deleted {len(old_vector_ids)} old vectors")
                except Exception as e:
                    logger.error(f"Failed to delete old vectors: {e}")
                    
            # Await the processing task synchronously
            target_version = doc.get("version", 1) + 1
            await knowledge_service._process_document_task(
                company_id=company_id,
                kb_id=doc["knowledge_base_id"],
                doc_id=doc_id,
                storage_path=storage_path,
                filename=filename,
                content_type=content_type,
                target_version=target_version
            )
            
            # Fetch updated doc
            updated_doc = await col_documents().find_one({"_id": ObjectId(doc_id)})
            new_chunk_count = updated_doc.get("chunk_count", 0)
            status = updated_doc.get("status", "unknown")
            
            report_lines.append(f"{company_id:<26} | {filename[:30]:<30} | {old_chunk_count:<12} | {new_chunk_count:<12} | {status}")
            
        except Exception as e:
            logger.error(f"Failed to process {filename}: {e}")
            report_lines.append(f"{company_id:<26} | {filename[:30]:<30} | {old_chunk_count:<12} | ERROR        | failed")
            
    logger.info("Rebuild complete. Generating report.")
    
    print("\n\n" + "\n".join(report_lines) + "\n" + "="*80)

if __name__ == "__main__":
    asyncio.run(main())
