import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

interface Citation {
  entity_id: string;
  name: string;
  entity_type: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const navigate = useNavigate();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || streaming) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setStreaming(true);

    // Add placeholder assistant message
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      let fullText = "";
      let citations: Citation[] = [];

      for await (const chunk of api.chat(userMessage)) {
        if (chunk.text) {
          fullText += chunk.text;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: fullText };
            return updated;
          });
          scrollToBottom();
        }
        if (chunk.citations) {
          citations = chunk.citations;
        }
      }

      // Update final message with citations
      if (citations.length > 0) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = { role: "assistant", content: fullText, citations };
          return updated;
        });
      }
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: `Error: ${err}`,
        };
        return updated;
      });
    }

    setStreaming(false);
    scrollToBottom();
  };

  return (
    <div className="flex flex-col h-[calc(100vh-52px)]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.length === 0 && (
            <div className="text-center text-m3-muted py-20">
              <p className="text-xl mb-2">Ask your knowledge base anything</p>
              <p className="text-sm">Your entity knowledge graph is used as context for answers</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] rounded-xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-m3-accent text-white"
                    : "bg-m3-surface border border-m3-border"
                }`}
              >
                <div className="prose">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                </div>
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-3 pt-2 border-t border-m3-border flex flex-wrap gap-1">
                    {msg.citations.map((c) => (
                      <button
                        key={c.entity_id}
                        onClick={() => navigate(`/entities/${c.entity_id}`)}
                        className="text-xs bg-m3-bg px-2 py-1 rounded hover:bg-m3-border transition-colors"
                      >
                        {c.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-m3-border p-4">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto flex gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question..."
            className="flex-1 bg-m3-surface border border-m3-border rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-m3-accent"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="px-6 py-3 bg-m3-accent text-white rounded-xl text-sm hover:bg-m3-accent-hover transition-colors disabled:opacity-50"
          >
            {streaming ? "..." : "Send"}
          </button>
        </form>
      </div>
    </div>
  );
}
