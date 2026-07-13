import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.call import Call
from app.models.event import CallEvent
from app.services.storage.factory import get_storage_backend

logger = logging.getLogger(__name__)

def create_call(
    db: Session, 
    fileobj, 
    filename: str, 
    mime_type: str, 
    file_size: int, 
    metadata: Optional[Dict[str, Any]] = None
) -> Call:
    """
    Creates a Call record in the database and writes its audio file to storage.
    If the database operation fails, the stored file is deleted (atomic rollback).
    """
    storage = get_storage_backend()
    storage_path = None
    
    try:
        # 1. Save file to storage
        storage_path = storage.save(fileobj, filename)
        logger.info(f"Saved file '{filename}' to storage: {storage_path}")
        
        # 2. Register call in database
        db_call = Call(
            filename=filename,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size_bytes=file_size,
            status="PENDING"
        )
        db.add(db_call)
        db.flush()  # Generates db_call.id
        
        # Create initial status change event
        event = CallEvent(
            call_id=db_call.id,
            event_type="STATUS_CHANGE",
            payload={"from_status": None, "to_status": "PENDING"}
        )
        db.add(event)
        
        db.commit()
        logger.info(f"Successfully registered call {db_call.id} in DB with status PENDING")
        return db_call
        
    except Exception as e:
        # Atomic rollback: ensure storage file is deleted if DB transaction fails
        logger.error(f"Failed to save call to database: {e}. Executing atomic rollback.")
        db.rollback()
        
        if storage_path:
            try:
                storage.delete(storage_path)
                logger.info(f"Cleaned up file at storage path: {storage_path}")
            except Exception as clean_err:
                logger.error(f"Failed to delete stored file during rollback: {clean_err}")
                
        raise e
