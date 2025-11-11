from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional, List
import logging

from .config import get_settings
from .models.schemas import (
    DocumentUploadResponse,
    QueryRequest,
    QueryResponse,
    UserDocumentsResponse,
    HealthCheckResponse,
    DocumentMetadata
)
from .services.walrus_service import WalrusService
from .services.sui_service import SuiService
from .services.rag_service import RAGService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    debug=settings.debug
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
walrus_service = WalrusService()
sui_service = SuiService()
rag_service = RAGService()


@app.get("/", response_model=HealthCheckResponse)
async def root():
    """Root endpoint with health check"""
    return {
        "status": "healthy",
        "services": {
            "walrus": "configured",
            "sui": "configured" if settings.sui_package_id else "not_configured",
            "rag": "ready",
            "openai": "configured" if settings.openai_api_key else "not_configured"
        }
    }


@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "services": {
            "walrus": "online",
            "sui": "online",
            "rag": "online"
        }
    }


@app.post("/upload-document", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    wallet_address: str = Form(...),
    is_public: bool = Form(False)
):
    """
    Upload a document to Walrus, mint NFT on Sui, and process for RAG

    Args:
        file: Document file (PDF, TXT, etc.)
        wallet_address: User's Sui wallet address
        is_public: Whether the document should be public
    """
    try:
        logger.info(f"Uploading document: {file.filename} for wallet: {wallet_address}")

        # Read file content
        file_content = await file.read()

        # Step 1: Upload to Walrus
        logger.info("Uploading to Walrus...")
        walrus_result = await walrus_service.upload_blob(file_content)
        blob_id = walrus_result["blob_id"]
        logger.info(f"Uploaded to Walrus: {blob_id}")

        # Step 2: Mint NFT on Sui (if package is configured)
        sui_result = None
        if settings.sui_package_id:
            try:
                logger.info("Minting document NFT on Sui...")
                sui_result = sui_service.mint_document(
                    name=file.filename,
                    walrus_blob_id=blob_id,
                    is_public=is_public,
                    signer_address=wallet_address
                )
                logger.info(f"Minted on Sui: {sui_result['transaction_digest']}")
            except Exception as e:
                logger.error(f"Sui minting failed: {str(e)}")
                # Continue even if Sui fails
                sui_result = {
                    "transaction_digest": "error",
                    "status": "failed",
                    "error": str(e)
                }
        else:
            logger.warning("Sui package not configured, skipping NFT minting")
            sui_result = {
                "transaction_digest": "not_configured",
                "status": "skipped"
            }

        # Step 3: Process document for RAG
        logger.info("Processing document for RAG...")
        rag_result = await rag_service.process_document(
            blob_id=blob_id,
            content=file_content,
            filename=file.filename,
            metadata={
                "owner": wallet_address,
                "is_public": is_public
            }
        )
        logger.info(f"RAG processing complete: {rag_result['chunks_created']} chunks created")

        return DocumentUploadResponse(
            walrus_blob_id=blob_id,
            sui_transaction_digest=sui_result["transaction_digest"],
            document_id=sui_result.get("document_object_id"),
            message="Document uploaded and processed successfully"
        )

    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """
    Query documents using RAG

    Args:
        request: Query request with question and optional filters
    """
    try:
        logger.info(f"Querying: {request.question}")

        # If wallet address is provided, get user's documents
        document_ids = request.document_ids
        if request.wallet_address and not document_ids:
            try:
                user_docs = sui_service.get_user_documents(request.wallet_address)
                document_ids = [doc["walrus_blob_id"] for doc in user_docs]
                logger.info(f"Found {len(document_ids)} documents for user")
            except Exception as e:
                logger.warning(f"Failed to get user documents: {str(e)}")

        # Query RAG system
        result = await rag_service.query_documents(
            question=request.question,
            document_ids=document_ids
        )

        return QueryResponse(**result)

    except Exception as e:
        logger.error(f"Query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents/{wallet_address}", response_model=UserDocumentsResponse)
async def get_user_documents(wallet_address: str):
    """
    Get all documents owned by a wallet address

    Args:
        wallet_address: Sui wallet address
    """
    try:
        logger.info(f"Getting documents for wallet: {wallet_address}")

        if not settings.sui_package_id:
            return UserDocumentsResponse(
                documents=[],
                total=0
            )

        documents = sui_service.get_user_documents(wallet_address)

        return UserDocumentsResponse(
            documents=[DocumentMetadata(**doc) for doc in documents],
            total=len(documents)
        )

    except Exception as e:
        logger.error(f"Failed to get documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents/{wallet_address}/{document_id}")
async def get_document(wallet_address: str, document_id: str):
    """
    Get a specific document's metadata

    Args:
        wallet_address: Sui wallet address
        document_id: Document object ID
    """
    try:
        if not settings.sui_package_id:
            raise HTTPException(status_code=404, detail="Sui not configured")

        document = sui_service.get_document(document_id)

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Verify ownership (optional, for private documents)
        if not document["is_public"]:
            if not sui_service.verify_ownership(document_id, wallet_address):
                raise HTTPException(status_code=403, detail="Access denied")

        return DocumentMetadata(**document)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{blob_id}")
async def download_document(blob_id: str, wallet_address: Optional[str] = None):
    """
    Download a document from Walrus

    Args:
        blob_id: Walrus blob ID
        wallet_address: Optional wallet address for access control
    """
    try:
        logger.info(f"Downloading blob: {blob_id}")

        # TODO: Add access control based on document ownership
        # For now, allow all downloads

        content = await walrus_service.download_blob(blob_id)

        return StreamingResponse(
            iter([content]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={blob_id}"
            }
        )

    except Exception as e:
        logger.error(f"Download failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents/{blob_id}")
async def delete_document(blob_id: str, wallet_address: str):
    """
    Delete a document's RAG embeddings

    Args:
        blob_id: Walrus blob ID
        wallet_address: Wallet address for verification
    """
    try:
        logger.info(f"Deleting document: {blob_id}")

        # TODO: Verify ownership before deletion

        result = rag_service.delete_document_embeddings(blob_id)

        return {
            "message": "Document embeddings deleted",
            "blob_id": blob_id,
            "deleted_chunks": result["deleted_chunks"]
        }

    except Exception as e:
        logger.error(f"Delete failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/{blob_id}")
async def get_document_stats(blob_id: str):
    """
    Get statistics about a document

    Args:
        blob_id: Walrus blob ID
    """
    try:
        stats = rag_service.get_document_stats(blob_id)
        return stats

    except Exception as e:
        logger.error(f"Failed to get stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
