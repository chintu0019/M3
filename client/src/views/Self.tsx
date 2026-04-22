import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import SlotView from "../components/SlotView";

const SLOT_ORDER = ["Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline"];

export default function Self() {
  const { data, error, loading } = useApi(() => api.self());
  if (loading) return <div className="p-6 text-m3-muted">loading…</div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!data) return null;
  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Self</h1>
      {SLOT_ORDER.map((name) => (
        <SlotView key={name} name={name} content={data.slots[name] ?? "_(empty)_"} />
      ))}
    </div>
  );
}
