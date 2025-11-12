import os
from typing import List, Optional, Dict
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.docstore.document import Document
import PyPDF2
from io import BytesIO
from ..config import get_settings


class RAGService:
    """Service for RAG (Retrieval-Augmented Generation) operations"""

    def __init__(self):
        self.settings = get_settings()

        # Initialize OpenAI
        os.environ["OPENAI_API_KEY"] = self.settings.openai_api_key
        self.embeddings = OpenAIEmbeddings()

        # Initialize ChromaDB
        self.vectorstore = Chroma(
            persist_directory=self.settings.chroma_persist_directory,
            embedding_function=self.embeddings
        )

        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            length_function=len,
        )

        # Initialize LLM
        self.llm = ChatOpenAI(
            temperature=self.settings.llm_temperature,
            model="gpt-3.5-turbo"
        )

        # Custom prompt template
        self.prompt_template = """Use the following pieces of context to answer the question at the end.
If you don't know the answer, just say that you don't know, don't try to make up an answer.

Context:
{context}

Question: {question}

Answer: """

        self.PROMPT = PromptTemplate(
            template=self.prompt_template,
            input_variables=["context", "question"]
        )

    def extract_text_from_pdf(self, content: bytes) -> str:
        """
        Extract text from PDF content

        Args:
            content: PDF file as bytes

        Returns:
            Extracted text
        """
        try:
            pdf_file = BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"

            return text

        except Exception as e:
            raise Exception(f"Failed to extract text from PDF: {str(e)}")

    def extract_text_from_file(self, content: bytes, filename: str) -> str:
        """
        Extract text from file based on extension

        Args:
            content: File content as bytes
            filename: Original filename

        Returns:
            Extracted text
        """
        extension = filename.lower().split('.')[-1]

        if extension == 'pdf':
            return self.extract_text_from_pdf(content)
        elif extension in ['txt', 'md', 'py', 'js', 'java', 'cpp', 'c', 'h']:
            return content.decode('utf-8', errors='ignore')
        else:
            # Try to decode as text
            try:
                return content.decode('utf-8', errors='ignore')
            except:
                raise Exception(f"Unsupported file type: {extension}")

    async def process_document(
        self,
        blob_id: str,
        content: bytes,
        filename: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Process document for RAG system

        Args:
            blob_id: Walrus blob ID
            content: File content
            filename: Original filename
            metadata: Additional metadata

        Returns:
            Processing result
        """
        try:
            # Extract text
            text = self.extract_text_from_file(content, filename)

            # Create chunks
            chunks = self.text_splitter.split_text(text)

            # Prepare metadata for each chunk
            metadatas = []
            for i, chunk in enumerate(chunks):
                chunk_metadata = {
                    "walrus_blob_id": blob_id,
                    "filename": filename,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
                if metadata:
                    chunk_metadata.update(metadata)
                metadatas.append(chunk_metadata)

            # Add to vector store
            self.vectorstore.add_texts(
                texts=chunks,
                metadatas=metadatas
            )

            # Persist the changes
            self.vectorstore.persist()

            return {
                "success": True,
                "blob_id": blob_id,
                "chunks_created": len(chunks),
                "text_length": len(text)
            }

        except Exception as e:
            raise Exception(f"Failed to process document: {str(e)}")

    async def query_documents(
        self,
        question: str,
        document_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None
    ) -> Dict:
        """
        Query documents using RAG

        Args:
            question: User's question
            document_ids: Optional list of blob IDs to filter
            top_k: Number of results to return

        Returns:
            Answer with sources
        """
        try:
            k = top_k or self.settings.similarity_top_k

            # Prepare filter
            search_kwargs = {"k": k}
            if document_ids:
                search_kwargs["filter"] = {
                    "walrus_blob_id": {"$in": document_ids}
                }

            # Perform similarity search
            docs = self.vectorstore.similarity_search(
                question,
                **search_kwargs
            )

            if not docs:
                return {
                    "answer": "I couldn't find any relevant information in the documents to answer your question.",
                    "sources": [],
                    "question": question
                }

            # Build context from retrieved documents
            context = "\n\n".join([doc.page_content for doc in docs])

            # Generate answer using LLM
            formatted_prompt = self.PROMPT.format(
                context=context,
                question=question
            )

            answer = self.llm.predict(formatted_prompt)

            # Prepare sources
            sources = []
            for doc in docs:
                sources.append({
                    "blob_id": doc.metadata.get("walrus_blob_id", ""),
                    "excerpt": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                    "chunk_index": doc.metadata.get("chunk_index", 0)
                })

            return {
                "answer": answer,
                "sources": sources,
                "question": question
            }

        except Exception as e:
            raise Exception(f"Failed to query documents: {str(e)}")

    def delete_document_embeddings(self, blob_id: str) -> Dict:
        """
        Delete all embeddings for a document

        Args:
            blob_id: Walrus blob ID

        Returns:
            Deletion result
        """
        try:
            # Get all documents with this blob_id
            results = self.vectorstore.get(
                where={"walrus_blob_id": blob_id}
            )

            if results and 'ids' in results:
                # Delete by IDs
                self.vectorstore.delete(ids=results['ids'])
                self.vectorstore.persist()

                return {
                    "success": True,
                    "deleted_chunks": len(results['ids'])
                }

            return {
                "success": True,
                "deleted_chunks": 0
            }

        except Exception as e:
            raise Exception(f"Failed to delete document embeddings: {str(e)}")

    def get_document_stats(self, blob_id: str) -> Dict:
        """
        Get statistics about a document's embeddings

        Args:
            blob_id: Walrus blob ID

        Returns:
            Document statistics
        """
        try:
            results = self.vectorstore.get(
                where={"walrus_blob_id": blob_id}
            )

            if results and 'ids' in results:
                return {
                    "blob_id": blob_id,
                    "total_chunks": len(results['ids']),
                    "exists": True
                }

            return {
                "blob_id": blob_id,
                "total_chunks": 0,
                "exists": False
            }

        except Exception as e:
            raise Exception(f"Failed to get document stats: {str(e)}")
