"
Zenaipex AI - Auto Knowledge Base Updater

Automatically generates and maintains a living platform state document for each company.
Re-generated daily and reflects: active agents, knowledge base docs, recent conversation topics.
Old vectors are atomically replaced with new ones.

Usage:
  - Scheduled daily via APScheduler (registered in main.py lifespan)
  - On-demand via internal API: POST /internal/auto-kb/refresh
  - Runs for ALL companies if no company_id is specified
"
import logging
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Sentinel filename - identifies auto-generated documents in the DB
AUTO_DOC_FILENAME = _auto_platform_snapshot.txt


async def run_auto_kb_update_all() -> Dict[str, Any]:
    "Run auto KB update for ALL active companies. Called by the daily scheduler."
    from core.database import col_companies
    results = {success: 0, failed: 0, skipped: 0, errors: []}

    companies_cursor = col_companies().find({}, {_id: 1, name: 1})
    async for company in companies_cursor:
        company_id = str(company[_id])
        company_name = company.get(name, Unknown)
        try:
            result = await run_auto_kb_update_for_company(company_id, company_name)
            if result.get(skipped):
                results[skipped] += 1
            else:
                results[success] += 1
        except Exception as e:
            results[failed] += 1
            results[errors].append({company_id: company_id, error: str(e)})
            logger.error(f[AUTO_KB] Company {company_id} failed: {e})

    logger.info(f[AUTO_KB] Daily run complete: {results})
    return results


async def run_auto_kb_update_for_company(company_id: str, company_name: str = ") -> Dict[str, Any]:
 "Generate and index an auto-snapshot document for a single company."
 from core.database import col_documents
 from services.knowledge_service import get_or_create_default_kb

 if not company_name:
 from core.database import col_companies
 from bson import ObjectId
 try:
 c = await col_companies().find_one({_id: ObjectId(company_id)})
 company_name = c.get(name, Company) if c else Company
 except Exception:
 company_name = Company

 kb = await get_or_create_default_kb(company_id, company_name)
 kb_id = str(kb[_id])

 existing_auto_doc = await col_documents().find_one({
 company_id: company_id,
 filename: AUTO_DOC_FILENAME,
 })

 if existing_auto_doc:
 updated_at = existing_auto_doc.get(updated_at)
 if updated_at and isinstance(updated_at, datetime):
 age = (datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc if updated_at.tzinfo is None else updated_at.tzinfo)).total_seconds() / 3600
 if age < 20:
 logger.info(f[AUTO_KB] Skip {company_id} - updated {age:.1f}h ago)
 return {status: skipped, reason: recent_update}

 snapshot_text = await _generate_snapshot_document(company_id, company_name)
 new_hash = hashlib.sha256(snapshot_text.encode(utf-8)).hexdigest()

 if existing_auto_doc and existing_auto_doc.get(content_hash) == new_hash:
 logger.info(f[AUTO_KB] Skip {company_id} - content unchanged)
 return {status: skipped, reason: content_unchanged}

 await _ingest_auto_doc(company_id, kb_id, snapshot_text, new_hash, existing_auto_doc)
 return {status: updated, company_id: company_id, kb_id: kb_id}


async def _generate_snapshot_document(company_id: str, company_name: str) -> str:
 now = datetime.now(timezone.utc)
 lines = []
 lines.append(f# {company_name} - Platform Knowledge Snapshot)
 lines.append(fAuto-generated: {now.strftime('%Y-%m-%d %H:%M UTC')})
 lines.append(fCompany ID: {company_id})
 lines.append()
 lines.append(---)
 lines.extend(await _build_company_profile_section(company_id, company_name))
 lines.extend(await _build_agents_section(company_id))
 lines.extend(await _build_documents_section(company_id))
 lines.extend(await _build_recent_topics_section(company_id))
 lines.append(---)
 lines.append(fEND OF AUTO-SNAPSHOT - {company_name})
 lines.append(fNext update: {(now + timedelta(days=1)).strftime('%Y-%m-%d')} UTC)
 return \n.join(lines)


async def _build_company_profile_section(company_id: str, company_name: str) -> List[str]:
 from core.database import col_companies
 from bson import ObjectId
 lines = [## Company Profile, ]
 try:
 company = await col_companies().find_one({_id: ObjectId(company_id)})
 if company:
 lines.append(fCompany Name: {company.get('name', company_name)})
 for field in [industry, description, about, website, email, phone, address, location]:
 val = company.get(field)
 if val:
 lines.append(f{field.title()}: {str(val)[:500]})
 except Exception as e:
 lines.append(f(Profile unavailable: {e}))
 lines.append()
 return lines


async def _build_agents_section(company_id: str) -> List[str]:
 from core.database import col_agents
 lines = [## Active AI Agents, ]
 try:
 count = 0
 async for agent in col_agents().find({company_id: company_id, is_active: True}):
 count += 1
 lines.append(f### Agent {count}: {agent.get('name', 'Unnamed Agent')})
 lines.append(f  Type: {agent.get('agent_type', 'company_customer_agent')})
 lines.append(f  Language: {agent.get('default_language', 'en-IN')} | Voice: {agent.get('tts_voice', 'ritu')})
 if agent.get(welcome_message):
 lines.append(f  Welcome: {agent['welcome_message'][:200]})
 if agent.get(system_prompt):
 lines.append(f  Persona: {agent['system_prompt'][:300].replace(chr(10), ' ')}...)
 lines.append()
 if count == 0:
 lines.append(No active agents.)
 lines.append()
 except Exception as e:
 lines.append(f(Agent data unavailable: {e}))
 lines.append()
 return lines


async def _build_documents_section(company_id: str) -> List[str]:
 from core.database import col_documents
 lines = [## Knowledge Base Documents, ]
 try:
 count = 0
 cursor = col_documents().find(
 {company_id: company_id, status: ready, filename: {: AUTO_DOC_FILENAME}},
 {filename: 1, chunk_count: 1, updated_at: 1, file_size_bytes: 1}
 ).sort(updated_at, -1).limit(50)
 async for doc in cursor:
 count += 1
 fname = doc.get(filename, unknown)
 chunks = doc.get(chunk_count, 0)
 updated = doc.get(updated_at)
 updated_str = updated.strftime(%Y-%m-%d) if isinstance(updated, datetime) else ?
 size_kb = round(doc.get(file_size_bytes, 0) / 1024, 1) if doc.get(file_size_bytes) else ?
 lines.append(f  - {fname} ({chunks} chunks, {size_kb} KB, updated: {updated_str}))
 lines.append(f\nTotal Documents: {count})
 lines.append()
 except Exception as e:
 lines.append(f(Document data unavailable: {e}))
 lines.append()
 return lines


async def _build_recent_topics_section(company_id: str) -> List[str]:
 from core.database import col_messages
 lines = [## Recent User Questions (Last 7 Days), ]
 try:
 since = datetime.now(timezone.utc) - timedelta(days=7)
 questions = []
 async for msg in col_messages().find(
 {company_id: company_id, role: user, timestamp: {: since}},
 {content: 1}
 ).sort(timestamp, -1).limit(100):
 content = (msg.get(content) or ).strip()
 if content and len(content) > 5 and content not in questions:
 questions.append(content)
 if questions:
 lines.append(Questions users commonly ask:)
 for i, q in enumerate(questions[:30], 1):
 lines.append(f  {i}. {q[:200]})
 else:
 lines.append(  No recent conversation data.)
 lines.append()
 except Exception as e:
 lines.append(f(Conversation data unavailable: {e}))
 lines.append()
 return lines


async def _ingest_auto_doc(company_id: str, kb_id: str, content: str, content_hash: str, existing_doc: Optional[Dict[str, Any]]) -> None:
 from core.database import col_documents, col_knowledge_bases
 from bson import ObjectId
 from ai.semantic_chunker import SemanticChunker
 from ai.vector_store import NamespacedVectorStore

 kb = await col_knowledge_bases().find_one({_id: ObjectId(kb_id)})
 if not kb:
 raise RuntimeError(fKB {kb_id} not found)
 namespace = kb[pinecone_namespace]
 now = datetime.now(timezone.utc)

 if existing_doc:
 doc_id = str(existing_doc[_id])
 target_version = existing_doc.get(version, 1) + 1
 await col_documents().update_one({_id: existing_doc[_id]}, {: {status: processing, updated_at: now}})
 else:
 target_version = 1
 result = await col_documents().insert_one({
 company_id: company_id, knowledge_base_id: kb_id,
 filename: AUTO_DOC_FILENAME, content_type: text/plain,
 file_size_bytes: len(content.encode(utf-8)), storage_path: ,
 content_hash: , status: processing, chunk_count: 0,
 vector_ids: [], version: 1, auto_generated: True,
 error_message: None, created_at: now, updated_at: now,
 })
 doc_id = str(result.inserted_id)
 existing_doc = {_id: result.inserted_id}

 try:
 chunker = SemanticChunker(max_chunk_size=1500)
 chunk_dicts = chunker.chunk(content)
 chunks = [c[text] for c in chunk_dicts]

 vs = NamespacedVectorStore(namespace=namespace)
 embeddings = vs.generate_embeddings(chunks)

 vectors, vector_ids = [], []
 for i, (cd, emb) in enumerate(zip(chunk_dicts, embeddings)):
 vh = hashlib.md5(cd[text].encode()).hexdigest()
 vid = f{company_id}_{doc_id}_auto_v{target_version}_{i}_{vh[:8]}
 vector_ids.append(vid)
 cm = cd.get(metadata, {})
 vectors.append({id: vid, values: emb, metadata: {
 text: cd[text], source: AUTO_DOC_FILENAME,
 document_id: doc_id, company_id: company_id,
 chunk_index: i, chunk_id: vid,
 module_name: cm.get(module_name, Platform Snapshot),
 section: cm.get(section, Auto-Generated),
 content_type: auto_snapshot,
 chunk_type: cm.get(chunk_type, paragraph),
 page_start: cm.get(page_start, 1), page_end: cm.get(page_end, 1),
 parent_section: Platform Snapshot, source_type: text/plain,
 document_version: target_version, updated_at: now.isoformat(),
 }})

 t0 = time.time()
 await vs.upsert_vectors(vectors)
 logger.info(f[AUTO_KB] Upserted {len(vectors)} vectors in {time.time()-t0:.2f}s for {company_id})

 old_doc = await col_documents().find_one({_id: ObjectId(doc_id)})
 old_ids = old_doc.get(vector_ids, []) if old_doc else []

 await col_documents().update_one({_id: ObjectId(doc_id)}, {: {
 status: ready, version: target_version, content_hash: content_hash,
 extracted_text: content[:10000], chunk_count: len(chunks),
 vector_ids: vector_ids, auto_generated: True, error_message: None, updated_at: now,
 }})

 if old_ids and target_version > 1:
 stale = [v for v in old_ids if v not in vector_ids]
 if stale:
 await vs.delete_vectors(stale)
 logger.info(f[AUTO_KB] Cleaned {len(stale)} stale vectors for {company_id})

 logger.info(f[AUTO_KB] Done for {company_id} v{target_version} ({len(chunks)} chunks))

 except Exception as e:
 await col_documents().update_one({_id: ObjectId(doc_id)}, {: {status: error, error_message: str(e), updated_at: now}})
 logger.error(f[AUTO_KB] Ingest failed for {company_id}: {e})
 raise
