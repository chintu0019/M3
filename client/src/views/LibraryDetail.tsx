import { useParams, useNavigate } from "react-router-dom";

export default function LibraryDetail() {
  const { id } = useParams();
  const navigate = useNavigate();

  return (
    <div className="max-w-4xl mx-auto p-6">
      <button
        onClick={() => navigate(-1)}
        className="text-m3-muted hover:text-m3-text mb-4"
      >
        ← Back
      </button>
      <h1 className="text-2xl font-bold mb-6">Library Detail</h1>
      <p className="text-m3-muted">Item ID: {id}</p>
    </div>
  );
}
