import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bell } from "lucide-react";
import api from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function MessageBell() {
  const { user } = useAuth();
  const [count, setCount] = useState(0);
  const poll = async () => {
    try { const { data } = await api.get("/messages/unread-count"); setCount(data?.unread || 0); }
    catch {}
  };
  useEffect(() => {
    if (!user || !user.role) return;
    poll();
    const t = setInterval(poll, 30000);
    return () => clearInterval(t);
  }, [user]);
  if (!user || !user.role) return null;
  const to = user.role === "admin" ? "/admin/enquiries" : "/dashboard/orders";
  return (
    <Link to={to} data-testid="message-bell" className="relative inline-flex items-center px-2 py-2 text-[#0A1128] hover:text-[#00509E]" title={count ? `${count} unread messages` : "No unread messages"}>
      <Bell size={18} />
      {count > 0 && (
        <span data-testid="message-bell-count" className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center text-[10px] font-bold text-white bg-[#A11B1B] rounded-full">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
