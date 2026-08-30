import { useState } from "react";
import api from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default function TrackOrderPage() {
  const [tn, setTn] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const track = async (e) => {
    e.preventDefault();
    setErr(""); setResult(null);
    try {
      const { data } = await api.get(`/orders/track/${encodeURIComponent(tn.trim())}`);
      setResult(data);
    } catch { setErr("Order not found. Please check the tracking number."); }
  };

  return (
    <div>
      <Header />
      <div className="container-page py-10 max-w-3xl">
        <h1 className="font-serif text-3xl font-bold text-[#0A1128]">Track Order</h1>
        <p className="text-[#4B5563] mt-1">Enter your tracking number (e.g. ZAX-2026-000001)</p>
        <form onSubmit={track} className="mt-6 flex gap-2" data-testid="track-form">
          <input className="zx-input" placeholder="ZAX-YYYY-NNNNNN" value={tn} onChange={e=>setTn(e.target.value)} data-testid="track-input" required />
          <button className="zx-btn-primary" data-testid="track-submit-btn">Track</button>
        </form>
        {err && <div className="text-[#A11B1B] mt-3 text-sm" data-testid="track-error">{err}</div>}
        {result && (
          <div className="zx-card mt-6" data-testid="track-result">
            <div className="text-xs uppercase text-[#00509E] font-semibold">Order</div>
            <div className="font-serif text-xl font-bold text-[#0A1128]">{result.order_number}</div>
            <div className="text-sm text-[#4B5563]">{result.service_name}</div>
            <div className="mt-2 flex gap-2 flex-wrap">
              <span className="zx-badge zx-badge-blue">{result.order_status}</span>
              <span className="zx-badge zx-badge-gray">Payment: {result.payment_status}</span>
            </div>
            <div className="mt-6">
              <div className="text-sm font-semibold text-[#0A1128] mb-2">Status History</div>
              <ol className="relative border-l border-[#E5E7EB] pl-4 space-y-4">
                {result.history.map((h, i) => (
                  <li key={i} className="text-sm">
                    <div className="absolute -left-1.5 w-3 h-3 bg-[#00509E] rounded-sm"></div>
                    <div className="text-[#0A1128] font-semibold">{h.to_status.replace(/_/g,' ')}</div>
                    <div className="text-xs text-[#6B7280]">{new Date(h.timestamp).toLocaleString()}</div>
                    {h.note && <div className="text-xs text-[#4B5563] mt-0.5">{h.note}</div>}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
