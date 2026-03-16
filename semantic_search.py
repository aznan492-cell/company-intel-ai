import os
import argparse
from dotenv import load_dotenv

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore

load_dotenv()

def run_search(query: str, top_k: int = 3):
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("❌ Error: PINECONE_API_KEY is missing from .env")
        print("Please add it before running semantic search.")
        return

    index_name = os.getenv("PINECONE_INDEX_NAME", "company-intel-db")
    print(f"🔍 Searching Pinecone Index '{index_name}' for:\n   \"{query}\"\n")

    # Reconnect to the same embedding model used for indexing
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    
    # Initialize the vector store connection
    try:
        vector_store = PineconeVectorStore(index_name=index_name, embedding=embeddings)
        
        # Perform the semantic search
        results = vector_store.similarity_search(query, k=top_k)

        if not results:
            print("No matching concepts found in the database.")
            return

        for i, doc in enumerate(results, 1):
            metadata = doc.metadata
            print("─" * 60)
            print(f"🎯 Result #{i} | Company: {metadata.get('company_name', 'Unknown').upper()} | Type: {metadata.get('chunk_type', 'Unknown')}")
            print("─" * 60)
            print(doc.page_content.strip())
            print()
            
    except Exception as e:
        print(f"❌ Search failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semantic search across company intelligence via Pinecone")
    parser.add_argument("query", type=str, help="The search concept (e.g. 'companies investing in AI safety')")
    parser.add_argument("--k", type=int, default=3, help="Number of results to return")
    args = parser.parse_args()
    
    run_search(args.query, args.k)
