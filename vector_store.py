import os
import json
from dotenv import load_dotenv

# We will use Google's embeddings since you are using Gemini as a primary model
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document

load_dotenv()

# Initialize Pinecone keys
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "company-intel-db")

def is_pinecone_configured():
    return bool(PINECONE_API_KEY)

def convert_to_documents(company_name: str, structured_data: dict) -> list[Document]:
    """
    Converts the structured JSON output into semantic LangChain Documents.
    We split it into logical chunks (e.g., Overview, Financials, Tech Stack)
    so the Vector DB can retrieve specific concepts effectively.
    """
    docs = []
    
    # Base Metadata attached to every chunk
    base_metadata = {
        "company_name": company_name,
        "source": "company-intel-pipeline"
    }
    
    # Chunk 1: General Info & Business Overview
    general_info = structured_data.get("general_info", {})
    overview_text = f"Company: {company_name}\nIndustry: {general_info.get('industry', 'Unknown')}\n"
    overview_text += f"Overview: {general_info.get('business_overview', 'No overview provided.')}\n"
    
    docs.append(Document(
        page_content=overview_text,
        metadata={**base_metadata, "chunk_type": "overview"}
    ))
    
    # Chunk 2: Market & Competitors
    market = structured_data.get("market_and_competitors", {})
    competitors = ", ".join(market.get("top_competitors", []))
    market_text = f"{company_name} operates in the {general_info.get('industry', 'Unknown')} sector.\n"
    market_text += f"Top Competitors: {competitors}\n"
    market_text += f"Market Position: {market.get('market_position', 'Unknown')}\n"
    
    docs.append(Document(
        page_content=market_text,
        metadata={**base_metadata, "chunk_type": "market"}
    ))
    
    # Chunk 3: Tech Stack & AI Usage
    tech = structured_data.get("technology_and_ai", {})
    ai_initiatives = " ".join(tech.get("ai_initiatives", []))
    tech_text = f"Technology & AI at {company_name}:\n"
    tech_text += f"Core Stack: {', '.join(tech.get('core_tech_stack', []))}\n"
    tech_text += f"AI Initiatives: {ai_initiatives}\n"
    
    docs.append(Document(
        page_content=tech_text,
        metadata={**base_metadata, "chunk_type": "technology"}
    ))
    
    # Add an aggregate raw dump for broader semantic searches
    docs.append(Document(
        page_content=f"Full intelligence profile for {company_name}: " + json.dumps(structured_data),
        metadata={**base_metadata, "chunk_type": "full_profile"}
    ))
    
    return docs

def index_company_data(company_name: str, structured_data: dict):
    """
    Generates embeddings for the structured data and upserts it into Pinecone.
    """
    if not is_pinecone_configured():
        print(f"  ⚠️  [Pinecone] Skipping vector indexing for {company_name}: PINECONE_API_KEY is missing.")
        return False
        
    print(f"  🌲 [Pinecone] Generating embeddings and indexing {company_name}...")
    
    try:
        # We use Google's embedding model since GEMINI_API_KEY is configured
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        
        # Convert JSON into text documents
        docs = convert_to_documents(company_name, structured_data)
        
        # Upsert documents to Pinecone
        PineconeVectorStore.from_documents(
            docs, 
            embeddings, 
            index_name=PINECONE_INDEX_NAME
        )
        
        print(f"  ✅ [Pinecone] Successfully indexed {len(docs)} semantic chunks for {company_name}.")
        return True
        
    except Exception as e:
        print(f"  ❌ [Pinecone] Failed to index {company_name}: {e}")
        return False
