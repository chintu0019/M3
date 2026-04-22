import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function SlotView({ name, content }: { name: string; content: string }) {
  const isEmpty = content.trim() === "_(empty)_" || content.trim() === "";
  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold mb-2">{name}</h2>
      {isEmpty ? (
        <p className="text-m3-muted text-sm italic">(empty)</p>
      ) : (
        <div className="text-sm leading-relaxed text-m3-text">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
    </section>
  );
}
