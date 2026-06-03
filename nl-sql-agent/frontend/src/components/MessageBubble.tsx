import { SqlPreview } from "./SqlPreview";

interface Message {
  role: "user" | "assistant";
  content: string;
  sql?: string | null;
  rowCount?: number | null;
}

export function MessageBubble({ role, content, sql, rowCount }: Message) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-slate-100 text-slate-800"
        }`}
      >
        <p className="whitespace-pre-wrap">{content}</p>
        {!isUser && sql && <SqlPreview sql={sql} rowCount={rowCount ?? null} />}
      </div>
    </div>
  );
}
