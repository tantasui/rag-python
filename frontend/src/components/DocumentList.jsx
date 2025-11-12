import { useState, useEffect } from 'react';
import { useCurrentAccount } from '@mysten/dapp-kit';
import axios from 'axios';

function DocumentList({ onDocumentsUpdate, refreshTrigger }) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const currentAccount = useCurrentAccount();

  useEffect(() => {
    if (currentAccount) {
      fetchDocuments();
    } else {
      setDocuments([]);
    }
  }, [currentAccount, refreshTrigger]);

  const fetchDocuments = async () => {
    if (!currentAccount) return;

    setLoading(true);
    setError(null);

    try {
      const response = await axios.get(
        `/api/documents/${currentAccount.address}`
      );

      setDocuments(response.data.documents);

      if (onDocumentsUpdate) {
        onDocumentsUpdate(response.data.documents);
      }

    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load documents');
      console.error('Fetch documents error:', err);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (timestamp) => {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleDateString();
  };

  if (!currentAccount) {
    return (
      <div className="document-list">
        <h2>My Documents</h2>
        <p className="info">Connect your wallet to view your documents</p>
      </div>
    );
  }

  return (
    <div className="document-list">
      <div className="list-header">
        <h2>My Documents</h2>
        <button onClick={fetchDocuments} disabled={loading} className="btn-secondary">
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading && <p>Loading documents...</p>}

      {!loading && documents.length === 0 && (
        <p className="info">No documents found. Upload your first document!</p>
      )}

      {!loading && documents.length > 0 && (
        <div className="documents-grid">
          {documents.map((doc) => (
            <div key={doc.id} className="document-card">
              <h3>{doc.name}</h3>
              <div className="document-details">
                <p>
                  <strong>Blob ID:</strong>{' '}
                  <span className="blob-id">{doc.walrus_blob_id.slice(0, 20)}...</span>
                </p>
                <p>
                  <strong>Uploaded:</strong> {formatDate(doc.uploaded_at)}
                </p>
                <p>
                  <strong>Visibility:</strong>{' '}
                  <span className={doc.is_public ? 'public' : 'private'}>
                    {doc.is_public ? 'Public' : 'Private'}
                  </span>
                </p>
              </div>
              <div className="document-actions">
                <a
                  href={`/api/download/${doc.walrus_blob_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-link"
                >
                  Download
                </a>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && documents.length > 0 && (
        <p className="document-count">
          Total: {documents.length} document(s)
        </p>
      )}
    </div>
  );
}

export default DocumentList;
