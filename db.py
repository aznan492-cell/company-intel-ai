import os
import json
import uuid
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

# For local Postgres (Docker)
from sqlalchemy import create_engine, Column, Integer, TEXT, TIMESTAMP, JSON, Index, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

load_dotenv()

# ── Local Postgres Setup (SQLAlchemy) ──────────────────────────────────────────

Base = declarative_base()

class RawResponse(Base):
    __tablename__ = "agent_raw_responses"
    id = Column(TEXT, primary_key=True)
    company_name = Column(TEXT, nullable=False)
    agent_name = Column(TEXT, nullable=False)
    model_name = Column(TEXT, nullable=False)
    raw_json = Column(JSON, nullable=False)
    retry_count = Column(Integer, default=0)
    status = Column(TEXT, default="success")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class ConsolidatedResult(Base):
    __tablename__ = "agent_consolidated_results"
    id = Column(TEXT, primary_key=True)
    company_name = Column(TEXT, nullable=False)
    model_name = Column(TEXT, default="judge")
    normalized_data = Column(JSON, nullable=False)
    retry_attempts = Column(Integer, default=0)
    validation_status = Column(TEXT, default="passed")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

# Database URL for local Postgres (provided by Docker Compose)
DATABASE_URL = os.getenv("DATABASE_URL")
engine = None
SessionLocal = None

if DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception as e:
        print(f"  ⚠️  [DB] Could not initialize SQLAlchemy: {e}")

# ── Supabase Setup (Fallback) ──────────────────────────────────────────────────

_supabase_client = None

def get_supabase():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client as sb_create
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            _supabase_client = sb_create(url, key)
    return _supabase_client

# ── DB Initialization ─────────────────────────────────────────────────────────

def init_db():
    """Create tables if they don't exist in local Postgres."""
    if engine:
        print("  🗄️  [DB] Initializing local database tables...")
        # Retry loop for Docker startup sync
        retries = 5
        while retries > 0:
            try:
                Base.metadata.create_all(bind=engine)
                print("  ✅ [DB] Local tables initialized.")
                return True
            except OperationalError:
                print("  ⏳ [DB] Waiting for Postgres to be ready...")
                time.sleep(2)
                retries -= 1
    return False

# ── Core Functions ─────────────────────────────────────────────────────────────

def store_raw_response(company_name, agent_name, model_name, raw_json, retry_count=0, status="success"):
    record_id = str(uuid.uuid4())
    
    # Try Local Postgres first
    if SessionLocal:
        try:
            with SessionLocal() as session:
                new_row = RawResponse(
                    id=record_id,
                    company_name=company_name,
                    agent_name=agent_name,
                    model_name=model_name,
                    raw_json=raw_json,
                    retry_count=retry_count,
                    status=status
                )
                session.add(new_row)
                session.commit()
                print(f"  💾 [DB] Stored raw response: {model_name} → Local Postgres")
                return record_id
        except Exception as e:
            print(f"  ⚠️  [DB] Local Postgres failed: {e}")

    # Fallback to Supabase
    sb = get_supabase()
    if sb:
        try:
            row = {
                "id": record_id,
                "company_name": company_name,
                "agent_name": agent_name,
                "model_name": model_name,
                "raw_json": raw_json,
                "retry_count": retry_count,
                "status": status,
            }
            sb.table("agent_raw_responses").insert(row).execute()
            print(f"  ☁️  [DB] Stored raw response: {model_name} → Supabase")
            return record_id
        except Exception as e:
            print(f"  ❌ [DB] Supabase failed: {e}")
    
    return None

def store_consolidated_result(company_name, normalized_data, retry_attempts=0, validation_status="passed", model_name="judge"):
    record_id = str(uuid.uuid4())
    
    # Try Local Postgres first
    if SessionLocal:
        try:
            with SessionLocal() as session:
                new_row = ConsolidatedResult(
                    id=record_id,
                    company_name=company_name,
                    model_name=model_name,
                    normalized_data=normalized_data,
                    retry_attempts=retry_attempts,
                    validation_status=validation_status
                )
                session.add(new_row)
                session.commit()
                print(f"  💾 [DB] Stored consolidated result → Local Postgres")
                return record_id
        except Exception as e:
            print(f"  ⚠️  [DB] Local Postgres failed: {e}")

    # Fallback to Supabase
    sb = get_supabase()
    if sb:
        try:
            row = {
                "id": record_id,
                "company_name": company_name,
                "model_name": model_name,
                "normalized_data": normalized_data,
                "retry_attempts": retry_attempts,
                "validation_status": validation_status,
            }
            sb.table("agent_consolidated_results").insert(row).execute()
            print(f"  ☁️  [DB] Stored consolidated result → Supabase")
            return record_id
        except Exception as e:
            print(f"  ❌ [DB] Supabase failed: {e}")
            
    return None

def is_db_configured():
    return bool(DATABASE_URL or (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")))
