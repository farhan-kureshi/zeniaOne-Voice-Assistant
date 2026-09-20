import time
from typing import List, Dict, Any
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
import config

class VectorStore:
    def __init__(self):
        # Initialize configuration
        self.api_key = config.PINECONE_API_KEY
        self.index_name = config.PINECONE_INDEX_NAME
        self.dimension = config.PINECONE_DIMENSION
        
        self.pc = None
        self.index = None
        self.model = None
        
        if self.api_key:
            self._init_services()
        else:
            print("⚠️ PINECONE_API_KEY not found. VectorStore running in uninitialized state.")
            
    def _init_services(self):
        print("🔌 Connecting to Pinecone...")
        self.pc = Pinecone(api_key=self.api_key)
        
        # Check if index exists, if not create it
        existing_indexes = [index_info["name"] for index_info in self.pc.list_indexes()]
        if self.index_name not in existing_indexes:
            print(f"🔨 Creating Pinecone index '{self.index_name}' with dimension {self.dimension}...")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric='cosine',
                spec=ServerlessSpec(
                    cloud='aws',
                    region='us-east-1'
                )
            )
            # Wait for index to be ready
            print(f"⏳ Waiting for index '{self.index_name}' to be ready...")
            while not self.pc.describe_index(self.index_name).status['ready']:
                time.sleep(1)
        
        self.index = self.pc.Index(self.index_name)
        print(f"✅ Connected to Pinecone index: {self.index_name}")
        
        # Initialize embedding model
        print(f"🧠 Loading embedding model: {config.EMBEDDING_MODEL}...")
        self.model = SentenceTransformer(config.EMBEDDING_MODEL)
        print("✅ Embedding model loaded.")
        
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not self.model:
            raise ValueError("Embedding model not initialized (missing API key?)")
        embeddings = self.model.encode(texts)
        return embeddings.tolist()
        
    def upsert_documents(self, documents: List[Dict[str, Any]], batch_size: int = 100):
        if not self.index:
            raise ValueError("Pinecone index not initialized")
            
        vectors = []
        for doc in documents:
            vectors.append({
                "id": doc["id"],
                "values": doc["values"],
                "metadata": doc["metadata"]
            })
            
        print(f"📤 Upserting {len(vectors)} vectors in batches of {batch_size}...")
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self.index.upsert(vectors=batch)
        print("✅ Upsert complete!")
            
    def similarity_search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not self.index or not self.model:
            raise ValueError("Pinecone or embedding model not initialized")
            
        query_embedding = self.generate_embeddings([query])[0]
        
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True
        )
        
        formatted_results = []
        for match in results["matches"]:
            formatted_results.append({
                "id": match["id"],
                "score": match["score"],
                "text": match["metadata"].get("text", ""),
                "source": match["metadata"].get("source", "")
            })
            
        return formatted_results
        
    def get_index_stats(self):
        if not self.index:
            return {}
        return self.index.describe_index_stats()

_vector_store_instance = None

def get_vector_store():
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore()
    return _vector_store_instance
