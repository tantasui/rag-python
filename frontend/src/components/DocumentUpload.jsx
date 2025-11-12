import { useState } from 'react';
import { useCurrentAccount } from '@mysten/dapp-kit';
import axios from 'axios';

function DocumentUpload({ onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [isPublic, setIsPublic] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const currentAccount = useCurrentAccount();

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setError(null);
    setSuccess(null);
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file');
      return;
    }

    if (!currentAccount) {
      setError('Please connect your wallet first');
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('wallet_address', currentAccount.address);
      formData.append('is_public', isPublic);

      const response = await axios.post('/api/upload-document', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      setSuccess(`Document uploaded successfully! Blob ID: ${response.data.walrus_blob_id}`);
      setFile(null);

      if (onUploadSuccess) {
        onUploadSuccess(response.data);
      }

      // Reset file input
      document.getElementById('file-input').value = '';

    } catch (err) {
      setError(err.response?.data?.detail || 'Upload failed. Please try again.');
      console.error('Upload error:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="document-upload">
      <h2>Upload Document</h2>

      <div className="upload-form">
        <div className="form-group">
          <label htmlFor="file-input">Select File (PDF, TXT, etc.)</label>
          <input
            id="file-input"
            type="file"
            onChange={handleFileChange}
            accept=".pdf,.txt,.md,.doc,.docx"
            disabled={loading || !currentAccount}
          />
        </div>

        {file && (
          <div className="file-info">
            <p>Selected: {file.name} ({(file.size / 1024).toFixed(2)} KB)</p>
          </div>
        )}

        <div className="form-group">
          <label>
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              disabled={loading}
            />
            Make document public
          </label>
        </div>

        <button
          onClick={handleUpload}
          disabled={loading || !file || !currentAccount}
          className="btn-primary"
        >
          {loading ? 'Uploading...' : 'Upload to Walrus & Sui'}
        </button>

        {!currentAccount && (
          <p className="warning">Please connect your wallet to upload documents</p>
        )}

        {error && <div className="error-message">{error}</div>}
        {success && <div className="success-message">{success}</div>}
      </div>
    </div>
  );
}

export default DocumentUpload;
