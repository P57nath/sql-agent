"use client";
import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { askAgent, AskResponse } from "@/lib/api";
import { MessageBubble } from "./MessageBubble";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sql?: string | null;
  rowCount?: number | null;
}

const SAMPLE_QUESTIONS = [
  "What are our top 5 customers by total revenue?",
  "How many orders were placed this week?",
  "Which product category has the highest average order value?",
  "Show me all pending orders with customer names.",
];

export function ChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(question: string) {
    if (!question.trim() || loading) return;
    setError(null);
    setInput("");
    setMessages((m) => [...m, { role: "user", content: question }]);
    setLoading(true);
    try {
      const res: AskResponse = await askAgent(question, sessionId);
      setSessionId(res.session_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          sql: res.sql_used,
          rowCount: res.row_count,
        },
      ]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-white">
      {/* Header */}
      <header className="border-b border-slate-200 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-800">
          Data Assistant
        </h1>
        <p className="text-sm text-slate-400">Ask questions about your data</p>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 && (
          <div className="mt-10 text-center">
            <p className="mb-4 text-sm text-slate-400">Try asking:</p>
            <div className="flex flex-col gap-2">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="mx-auto rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} {...m} />
        ))}
        {loading && (
          <div className="mb-4 flex justify-start">
            <div className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-500">
              Querying database…
            </div>
          </div>
        )}
        {error && (
          <p className="text-center text-xs text-red-500">{error}</p>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 px-6 py-4">
        <div className="flex items-center gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            placeholder="Ask about your data…"
            className="flex-1 rounded-xl border border-slate-200 px-4 py-2 text-sm outline-none focus:border-blue-400"
          />
          <button
            onClick={() => send(input)}
            disabled={loading || !input.trim()}
            className="rounded-xl bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-40"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
