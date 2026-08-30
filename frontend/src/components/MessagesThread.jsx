import { useEffect, useRef, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Send, MessageSquare } from "lucide-react";

export default function MessagesThread({ parentType, parentId }) {
  const [items, setItems] = useState([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef(null);

  const load = async () => {
    try {
      const { data } = await api.get(`/messages?parent_type=${parentType}&parent_id=${parentId}`);
      setItems(data);
    } catch {}
  };

  useEffect(() => { if (parentId) load(); /* eslint-disable-next-line */ }, [parentId, parentType]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [items]);

  const send = async (e) => {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    try {
      await api.post("/messages", { parent_type: parentType, parent_id: parentId, body });
      setBody(""); await load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="mt-4" data-testid={`messages-thread-${parentType}-${parentId}`}>
      <div className="font-semibold text-sm text-[#0A1128] flex items-center gap-1.5"><MessageSquare size={14}/> Messages</div>
      <div ref={listRef} className="mt-2 border border-[#E5E7EB] bg-[#F8F9FA] max-h-56 overflow-y-auto p-2 space-y-2">
        {items.length === 0 && <div className="text-xs text-[#6B7280] text-center py-3">No messages yet. Start the conversation.</div>}
        {items.map(m => {
          const mine = m.sender_role === "admin"; // will be styled by role
          return (
            <div key={m.id} className={`text-sm flex ${m.sender_role === "admin" ? "justify-start" : "justify-end"}`}>
              <div className={`max-w-[80%] px-3 py-1.5 border ${m.sender_role === "admin" ? "bg-white border-[#E5E7EB] text-[#0A1128]" : "bg-[#E7F0FA] border-[#C5DBF0] text-[#0A1128]"}`}>
                <div className="text-[10px] uppercase font-semibold tracking-wider text-[#6B7280]">
                  {m.sender_role === "admin" ? "ZEROAXIS" : (m.sender_name || "Customer")}
                  <span className="ml-1 text-[9px] font-normal">{new Date(m.created_at).toLocaleString()}</span>
                </div>
                <div className="whitespace-pre-wrap break-words">{m.body}</div>
              </div>
            </div>
          );
        })}
      </div>
      <form onSubmit={send} className="flex gap-2 mt-2">
        <input
          className="zx-input flex-1"
          placeholder="Type a message…"
          value={body}
          onChange={e=>setBody(e.target.value)}
          maxLength={4000}
          data-testid={`message-input-${parentType}-${parentId}`}
        />
        <button className="zx-btn-primary" disabled={busy || !body.trim()} data-testid={`message-send-${parentType}-${parentId}`}>
          <Send size={14}/> Send
        </button>
      </form>
    </div>
  );
}
