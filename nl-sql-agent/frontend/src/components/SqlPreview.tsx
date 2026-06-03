"use client";
import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface SqlPreviewProps {
  sql: string;
  rowCount: number | null;
}

export function SqlPreview({ sql, rowCount }: SqlPreviewProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-slate-400 hover:text-slate-600"
      >
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        View SQL
        {rowCount !== null && (
          <span className="ml-1 text-slate-300">· {rowCount} rows</span>
        )}
      </button>
      {open && (
        <pre className="mt-1 overflow-x-auto rounded bg-slate-900 p-3 text-green-400">
          {sql}
        </pre>
      )}
    </div>
  );
}
