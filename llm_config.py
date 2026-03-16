import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

load_dotenv()

def get_gemini_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0
    )

def get_groq_llm():
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0
    )

def get_openrouter_llm():
    return ChatOpenAI(
        model="google/gemma-2-9b-it",
        api_key=os.getenv("OPENROUTER_API_KEY"), # Changed to OPENROUTER_API_KEY for consistency
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        default_headers={
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "Company Intel",
        }
    )