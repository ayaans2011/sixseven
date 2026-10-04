import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import Header from "@/components/Header";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { LayoutDashboard, Users, FileText, ShoppingBag, CreditCard, Server, Bell, ClipboardList, Settings, Download, Upload, Paperclip, Trash2, Search, BarChart3, ArrowRightCircle, MessageCircle } from "lucide-react";
import MessagesThread from "@/components/MessagesThread";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

function bytesHuman(n) {
  if (!n && n !== 0) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n/1024).toFixed(1)} KB`;
  return `${(n/1024/1024).toFixed(2)} MB`;
}

function FileAttachments({ parentType, parentId }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = () => api.get(`/files/list?parent_type=${parentType}&parent_id=${parentId}`).then(r=>setFiles(r.data)).catch(()=>{});
  useEffect(()=>{ if(parentId) load(); /* eslint-disable-next-line */ }, [parentId]);
  const upload = async (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    if (f.size > 10 * 1024 * 1024) return toast.error("Max 10 MB per file");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("parent_type", parentType);
      fd.append("parent_id", parentId);
      fd.append("file", f);
      await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Uploaded"); load();
    } catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); e.target.value = ""; }
  };
  const download = async (f) => {
    try {
      const resp = await api.get(`/files/${f.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a"); a.href = url; a.download = f.original_name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=>URL.revokeObjectURL(url), 2000);
    } catch { toast.error("Download failed"); }
  };
  const remove = async (f) => {
    if (!confirm(`Remove ${f.original_name}?`)) return;
    try { await api.delete(`/files/${f.id}`); toast.success("Removed"); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  return (
    <div className="mt-4">
      <div className="flex items-center justify-between">
        <div className="font-semibold text-sm text-[#0A1128] flex items-center gap-1.5"><Paperclip size={14}/> Attachments</div>
        <label className="zx-btn-outline cursor-pointer text-xs" data-testid={`admin-upload-${parentType}-${parentId}`}>
          <Upload size={12}/> {busy ? "Uploading…" : "Upload"}
          <input type="file" className="hidden" onChange={upload} disabled={busy} />
        </label>
      </div>
      <div className="mt-2 space-y-1.5">
        {files.map(f => (
          <div key={f.id} className="flex items-center justify-between border border-[#E5E7EB] px-3 py-1.5 text-sm bg-white">
            <div className="min-w-0">
              <div className="truncate text-[#0A1128]">{f.original_name}</div>
              <div className="text-xs text-[#6B7280]">{bytesHuman(f.size)} · by {f.owner_email} · {new Date(f.created_at).toLocaleString()}</div>
            </div>
            <div className="flex gap-2 shrink-0">
              <button onClick={()=>download(f)} className="zx-link text-xs flex items-center gap-1" data-testid={`admin-download-${f.id}`}><Download size={12}/>Download</button>
              <button onClick={()=>remove(f)} className="text-[#A11B1B] text-xs flex items-center gap-1"><Trash2 size={12}/></button>
            </div>
          </div>
        ))}
        {files.length===0 && <div className="text-xs text-[#6B7280]">No attachments.</div>}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    UNPAID: "gray", PAYMENT_SUBMITTED: "amber", PENDING_VERIFICATION: "amber",
    PAYMENT_VERIFIED: "green", PAYMENT_REJECTED: "red", REFUNDED: "gray",
    CREATED: "blue", WORK_STARTED: "blue", IN_PROGRESS: "blue",
    READY_FOR_DELIVERY: "amber", COMPLETED: "green", CANCELLED: "red",
    new: "blue", responded: "green", closed: "gray", converted: "green",
  };
  return <span className={`zx-badge zx-badge-${map[status] || "gray"}`}>{String(status).replace(/_/g,' ')}</span>;
}

function Dash() {
  const [stats, setStats] = useState({});
  useEffect(()=>{ api.get("/admin/stats").then(r=>setStats(r.data)); },[]);
  const cards = [
    { k: "total_customers", label: "Total customers" },
    { k: "new_enquiries", label: "New enquiries" },
    { k: "active_orders", label: "Active orders" },
    { k: "pending_payments", label: "Pending payments" },
    { k: "verified_payments", label: "Verified payments" },
    { k: "completed_orders", label: "Completed orders" },
  ];
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Dashboard</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
        {cards.map(c => (
          <div key={c.k} className="zx-card" data-testid={`admin-stat-${c.k}`}>
            <div className="text-xs uppercase text-[#6B7280] font-semibold">{c.label}</div>
            <div className="font-serif text-2xl font-bold mt-1 text-[#0A1128]">{stats[c.k] ?? 0}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CustomerQRModal({ customer, onClose, onSaved }) {
  const [dataUrl, setDataUrl] = useState("");
  const [label, setLabel] = useState("");
  const [existing, setExisting] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get(`/admin/customers/${customer.id}/qr`).then(r => {
      setExisting(r.data);
      setLabel(r.data?.label || "");
    });
  }, [customer.id]);
  const onFile = (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    if (!f.type.startsWith("image/")) return toast.error("Please pick an image");
    if (f.size > 2 * 1024 * 1024) return toast.error("Max 2MB");
    const rd = new FileReader(); rd.onload = () => setDataUrl(rd.result); rd.readAsDataURL(f);
  };
  const save = async () => {
    if (!dataUrl && !existing?.data_url) return toast.error("Pick an image first");
    setBusy(true);
    try {
      await api.put(`/admin/customers/${customer.id}/qr`, { data_url: dataUrl || existing.data_url, label });
      toast.success("QR saved"); onSaved && onSaved(); onClose();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!confirm("Remove QR for this customer?")) return;
    await api.delete(`/admin/customers/${customer.id}/qr`);
    toast.success("QR removed"); onSaved && onSaved(); onClose();
  };
  const preview = dataUrl || existing?.data_url;
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40" onClick={onClose}>
      <div className="bg-white max-w-lg w-full p-6 border" onClick={e=>e.stopPropagation()} data-testid="customer-qr-modal">
        <div className="font-serif text-lg font-bold">Payment QR for {customer.name}</div>
        <div className="text-xs text-[#6B7280]">{customer.email}</div>
        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <label className="zx-label">QR image (PNG/JPG)</label>
            <input type="file" accept="image/*" onChange={onFile} className="zx-input" data-testid="customer-qr-file" />
            <label className="zx-label mt-3">Label / UPI ID (optional)</label>
            <input className="zx-input" value={label} onChange={e=>setLabel(e.target.value)} placeholder="e.g. zeroaxis@upi" data-testid="customer-qr-label" />
          </div>
          <div>
            <div className="zx-label">Preview</div>
            {preview ? <img src={preview} alt="QR" className="w-40 h-40 object-contain border border-[#E5E7EB] bg-white p-1" /> : <div className="w-40 h-40 border border-dashed border-[#E5E7EB] flex items-center justify-center text-xs text-[#6B7280]">No image</div>}
          </div>
        </div>
        <div className="mt-4 flex gap-2 justify-end">
          {existing?.data_url && <button className="zx-btn-outline" onClick={remove} data-testid="customer-qr-remove">Remove</button>}
          <button className="zx-btn-outline" onClick={onClose}>Cancel</button>
          <button className="zx-btn-primary" onClick={save} disabled={busy} data-testid="customer-qr-save">{busy?"Saving…":"Save QR"}</button>
        </div>
      </div>
    </div>
  );
}

function Customers() {
  const [items, setItems] = useState([]);
  const [qrFor, setQrFor] = useState(null);
  const load = () => api.get("/admin/customers").then(r=>setItems(r.data));
  useEffect(()=>{ load(); },[]);
  const toggle = async (id) => { await api.post(`/admin/customers/${id}/toggle`); load(); };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Customers</h2>
      <div className="overflow-x-auto mt-4"><table className="zx-table" data-testid="admin-customers-table"><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Payment QR</th><th>Status</th><th>Joined</th><th></th></tr></thead><tbody>
        {items.map(u => (
          <tr key={u.id}>
            <td>{u.name}</td><td>{u.email}</td><td>{u.phone||"—"}</td>
            <td>{u.has_qr ? <span className="zx-badge zx-badge-green">Uploaded</span> : <span className="zx-badge zx-badge-gray">Not set</span>}</td>
            <td>{u.disabled ? <StatusBadge status="CANCELLED" /> : <StatusBadge status="COMPLETED" />}</td>
            <td>{u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}</td>
            <td className="flex gap-3">
              <button onClick={()=>setQrFor(u)} className="zx-link text-sm" data-testid={`qr-customer-${u.id}`}>{u.has_qr?"Update QR":"Upload QR"}</button>
              <button onClick={()=>toggle(u.id)} className="zx-link text-sm" data-testid={`toggle-customer-${u.id}`}>{u.disabled?"Enable":"Disable"}</button>
            </td>
          </tr>
        ))}
        {items.length===0 && <tr><td colSpan="7" className="text-center py-6 text-[#6B7280]">No customers yet.</td></tr>}
      </tbody></table></div>
      {qrFor && <CustomerQRModal customer={qrFor} onClose={()=>setQrFor(null)} onSaved={load} />}
    </div>
  );
}

function Enquiries() {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [resp, setResp] = useState("");
  const [converting, setConverting] = useState(false);
  const load = () => api.get("/enquiries/admin/all").then(r=>setItems(r.data));
  useEffect(()=>{ load(); },[]);
  const respond = async () => {
    try { await api.post(`/enquiries/${sel.id}/respond`, { response: resp, status: "responded" }); toast.success("Response sent"); setSel(null); setResp(""); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const convert = async () => {
    if (!sel) return;
    if (!confirm(`Create an order from enquiry ${sel.enquiry_number}? A customer account will be auto-created if the enquirer isn't registered yet.`)) return;
    setConverting(true);
    try {
      const params = sel.service_id ? "" : "";
      const { data } = await api.post(`/enquiries/${sel.id}/convert${params}`);
      toast.success(`Order ${data.order_number} created${data.new_customer_created ? " (customer auto-created)" : ""}`);
      setSel(null); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setConverting(false); }
  };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Enquiries</h2>
      <div className="overflow-x-auto mt-4"><table className="zx-table" data-testid="admin-enquiries-table"><thead><tr><th>Number</th><th>Name</th><th>Service</th><th>Status</th><th></th></tr></thead><tbody>
        {items.map(e => (
          <tr key={e.id}>
            <td>{e.enquiry_number}</td><td>{e.name}<div className="text-xs text-[#6B7280]">{e.email}</div></td>
            <td>{e.service_name}</td><td><StatusBadge status={e.status} /></td>
            <td><button className="zx-link text-sm" onClick={()=>{setSel(e); setResp(e.admin_response||"");}} data-testid={`open-enquiry-${e.enquiry_number}`}>Open</button></td>
          </tr>
        ))}
      </tbody></table></div>
      {sel && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40 overflow-auto" onClick={()=>setSel(null)}>
          <div className="bg-white max-w-xl w-full p-6 border my-6" onClick={e=>e.stopPropagation()}>
            <div className="flex justify-between items-start">
              <div>
                <div className="font-serif text-xl font-bold">{sel.enquiry_number}</div>
                <div className="text-sm text-[#4B5563] mt-1">From: {sel.name} ({sel.email})</div>
                <div className="mt-1"><StatusBadge status={sel.status} /></div>
              </div>
              <button onClick={()=>setSel(null)}>✕</button>
            </div>
            <div className="text-sm mt-2"><b>Service:</b> {sel.service_name || "—"}</div>
            <div className="text-sm mt-1"><b>Requirement:</b> {sel.requirement}</div>
            <div className="text-sm mt-1"><b>Message:</b> {sel.message||"—"}</div>

            {sel.converted_order_id ? (
              <div className="mt-3 text-sm text-[#146C2E]">Converted to an order.</div>
            ) : sel.service_id ? (
              <button onClick={convert} disabled={converting} className="zx-btn-primary mt-3" data-testid={`convert-enquiry-${sel.enquiry_number}`}>
                <ArrowRightCircle size={14}/> {converting ? "Converting…" : "Convert to Order"}
              </button>
            ) : (
              <div className="mt-3 text-xs text-[#6B7280]">This enquiry has no service selected — respond asking which service, then convert once set.</div>
            )}

            <FileAttachments parentType="enquiry" parentId={sel.id} />
            <MessagesThread parentType="enquiry" parentId={sel.id} />

            <label className="zx-label mt-3">Admin response</label>
            <textarea rows={4} className="zx-input" value={resp} onChange={e=>setResp(e.target.value)} data-testid="enquiry-response-textarea"></textarea>
            <div className="mt-3 flex gap-2">
              <button className="zx-btn-primary" onClick={respond} data-testid="enquiry-send-response-btn">Send response</button>
              <button className="zx-btn-outline" onClick={()=>setSel(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AdminOrderQRBlock({ orderId }) {
  const [qr, setQr] = useState(null);
  const [dataUrl, setDataUrl] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.get(`/orders/${orderId}/qr`).then(r=>setQr(r.data));
  useEffect(()=>{ load(); }, [orderId]);
  const onFile = (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    if (!f.type.startsWith("image/")) return toast.error("Please pick an image");
    if (f.size > 2 * 1024 * 1024) return toast.error("Max 2MB");
    const rd = new FileReader(); rd.onload = () => setDataUrl(rd.result); rd.readAsDataURL(f);
  };
  const save = async () => {
    if (!dataUrl) return toast.error("Pick an image first");
    setBusy(true);
    try {
      await api.put(`/admin/orders/${orderId}/qr`, { data_url: dataUrl, label });
      toast.success("Order QR set"); setDataUrl(""); load();
    } catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const clearIt = async () => {
    if (!confirm("Remove order-specific QR? (customer default will apply)")) return;
    await api.delete(`/admin/orders/${orderId}/qr`);
    toast.success("Removed"); load();
  };
  return (
    <div className="zx-card mt-4">
      <div className="font-semibold text-sm text-[#0A1128]">Payment QR</div>
      <div className="text-xs text-[#6B7280]">Order-specific QR overrides the customer default.</div>
      <div className="mt-3 flex items-start gap-4">
        {qr?.data_url ? (
          <img src={qr.data_url} alt="QR" className="w-32 h-32 object-contain border border-[#E5E7EB] bg-white p-1" />
        ) : (
          <div className="w-32 h-32 border border-dashed border-[#E5E7EB] flex items-center justify-center text-xs text-[#6B7280]">No QR</div>
        )}
        <div className="flex-1 space-y-2">
          <input type="file" accept="image/*" onChange={onFile} className="zx-input" data-testid={`order-qr-file-${orderId}`} />
          <input className="zx-input" placeholder="Label (e.g. UPI ID) — optional" value={label} onChange={e=>setLabel(e.target.value)} />
          <div className="flex gap-2">
            <button className="zx-btn-primary" onClick={save} disabled={busy || !dataUrl} data-testid={`order-qr-save-${orderId}`}>Upload / Replace</button>
            {qr?.data_url && <button className="zx-btn-outline" onClick={clearIt}>Clear</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

const ORDER_STATUSES = ["CREATED","PAYMENT_SUBMITTED","PAYMENT_VERIFIED","WORK_STARTED","IN_PROGRESS","READY_FOR_DELIVERY","COMPLETED","CANCELLED"];

function Orders() {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [note, setNote] = useState("");
  const [newStatus, setNewStatus] = useState("");
  const [filters, setFilters] = useState({ q: "", status: "", payment_status: "", date_from: "", date_to: "" });
  const load = () => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k,v])=>{ if(v) params.set(k,v); });
    const qs = params.toString();
    return api.get(`/orders/admin/all${qs?`?${qs}`:""}`).then(r=>setItems(r.data));
  };
  useEffect(()=>{ load(); /* eslint-disable-next-line */ },[]);
  const applyFilters = (e) => { e?.preventDefault?.(); load(); };
  const reset = () => { setFilters({ q:"", status:"", payment_status:"", date_from:"", date_to:"" }); setTimeout(load, 0); };
  const exportCsv = async () => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k,v])=>{ if(v) params.set(k,v); });
    try {
      const resp = await api.get(`/orders/admin/export.csv?${params.toString()}`, { responseType: "blob" });
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a"); a.href = url;
      a.download = `zeroaxis-orders-${new Date().toISOString().slice(0,10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=>URL.revokeObjectURL(url), 2000);
    } catch { toast.error("Export failed"); }
  };
  const open = async (id) => { const { data } = await api.get(`/orders/${id}`); setSel(data); setNewStatus(data.order_status); setNote(""); };
  const updateStatus = async () => {
    try { await api.post(`/orders/${sel.id}/status`, { order_status: newStatus, note }); toast.success("Status updated"); open(sel.id); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const verifyPayment = async (action) => {
    try { await api.post(`/orders/${sel.id}/payment/verify`, { action, note }); toast.success(`Payment ${action}`); open(sel.id); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const downloadInvoice = async () => {
    try {
      const resp = await api.get(`/orders/${sel.id}/invoice.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a"); a.href = url; a.download = `invoice-${sel.order_number}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=>URL.revokeObjectURL(url), 2000);
    } catch { toast.error("Invoice not ready (requires payment verified)"); }
  };
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Orders</h2>
        <button className="zx-btn-outline" onClick={exportCsv} data-testid="admin-export-csv-btn"><Download size={14}/> Export CSV</button>
      </div>

      <form onSubmit={applyFilters} className="zx-card mt-4 grid grid-cols-1 md:grid-cols-6 gap-2" data-testid="admin-orders-filters">
        <div className="md:col-span-2 relative">
          <Search size={14} className="absolute left-2 top-2.5 text-[#6B7280]" />
          <input className="zx-input pl-7" placeholder="Search order#, customer, service…" value={filters.q} onChange={e=>setFilters({...filters, q: e.target.value})} data-testid="admin-orders-search" />
        </div>
        <select className="zx-input" value={filters.status} onChange={e=>setFilters({...filters, status: e.target.value})} data-testid="admin-filter-status">
          <option value="">Any status</option>
          {ORDER_STATUSES.map(s=><option key={s} value={s}>{s.replace(/_/g,' ')}</option>)}
        </select>
        <select className="zx-input" value={filters.payment_status} onChange={e=>setFilters({...filters, payment_status: e.target.value})} data-testid="admin-filter-payment">
          <option value="">Any payment</option>
          {["UNPAID","PENDING_VERIFICATION","PAYMENT_VERIFIED","PAYMENT_REJECTED","REFUNDED"].map(s=><option key={s} value={s}>{s.replace(/_/g,' ')}</option>)}
        </select>
        <input type="date" className="zx-input" value={filters.date_from} onChange={e=>setFilters({...filters, date_from: e.target.value})} data-testid="admin-filter-from" />
        <input type="date" className="zx-input" value={filters.date_to} onChange={e=>setFilters({...filters, date_to: e.target.value})} data-testid="admin-filter-to" />
        <div className="md:col-span-6 flex gap-2">
          <button className="zx-btn-primary" type="submit" data-testid="admin-apply-filters-btn">Apply filters</button>
          <button type="button" className="zx-btn-outline" onClick={reset} data-testid="admin-reset-filters-btn">Reset</button>
          <div className="text-xs text-[#6B7280] self-center">{items.length} result{items.length===1?"":"s"}</div>
        </div>
      </form>

      <div className="overflow-x-auto mt-4"><table className="zx-table" data-testid="admin-orders-table"><thead><tr><th>Number</th><th>Customer</th><th>Service</th><th>Amount</th><th>Payment</th><th>Status</th><th></th></tr></thead><tbody>
        {items.map(o => (
          <tr key={o.id}>
            <td>{o.order_number}</td><td>{o.customer_name}<div className="text-xs text-[#6B7280]">{o.customer_email}</div></td>
            <td>{o.service_name}</td><td>₹{Number(o.amount).toLocaleString('en-IN')}</td>
            <td><StatusBadge status={o.payment_status} /></td><td><StatusBadge status={o.order_status} /></td>
            <td><button className="zx-link text-sm" onClick={()=>open(o.id)} data-testid={`admin-open-order-${o.order_number}`}>Open</button></td>
          </tr>
        ))}
        {items.length===0 && <tr><td colSpan="7" className="text-center text-[#6B7280] py-6">No orders match the current filters.</td></tr>}
      </tbody></table></div>
      {sel && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40 overflow-auto" onClick={()=>setSel(null)}>
          <div className="bg-white max-w-2xl w-full p-6 border my-6" onClick={e=>e.stopPropagation()}>
            <div className="flex justify-between">
              <div>
                <div className="font-serif text-xl font-bold">{sel.order_number}</div>
                <div className="text-sm text-[#4B5563]">{sel.customer_name} — {sel.customer_email}</div>
              </div>
              <button onClick={()=>setSel(null)}>✕</button>
            </div>
            <div className="mt-2 flex gap-2 flex-wrap">
              <StatusBadge status={sel.order_status} />
              <span className="zx-badge zx-badge-gray">Payment: {sel.payment_status}</span>
            </div>
            <div className="text-sm mt-2"><b>Amount:</b> ₹{Number(sel.amount).toLocaleString('en-IN')}</div>
            <div className="text-sm"><b>Requirement:</b> {sel.requirement}</div>

            {sel.payment_status === "PAYMENT_VERIFIED" && (
              <button className="zx-btn-primary mt-3" onClick={downloadInvoice} data-testid={`admin-invoice-${sel.order_number}`}>
                <Download size={14}/> Download Invoice
              </button>
            )}

            <AdminOrderQRBlock orderId={sel.id} />
            <FileAttachments parentType="order" parentId={sel.id} />
            <MessagesThread parentType="order" parentId={sel.id} />

            {sel.payment_status === "PENDING_VERIFICATION" && (
              <div className="zx-card mt-4">
                <div className="font-semibold text-sm text-[#0A1128]">Payment to verify</div>
                {(sel.payments||[]).filter(p=>p.status==="PENDING_VERIFICATION").map(p=>(
                  <div key={p.id} className="text-sm text-[#4B5563] mt-1">Method: {p.method} · Ref: {p.reference} · Amount: ₹{p.amount}</div>
                ))}
                <textarea rows={2} className="zx-input mt-2" placeholder="Verification note (optional)" value={note} onChange={e=>setNote(e.target.value)} />
                <div className="mt-2 flex gap-2">
                  <button className="zx-btn-primary" onClick={()=>verifyPayment("verify")} data-testid="verify-payment-btn">Verify</button>
                  <button className="zx-btn-outline" onClick={()=>verifyPayment("reject")} data-testid="reject-payment-btn">Reject</button>
                </div>
              </div>
            )}

            <div className="mt-4">
              <div className="font-semibold text-sm">Update Status</div>
              <div className="flex gap-2 mt-2 flex-wrap">
                <select className="zx-input" value={newStatus} onChange={e=>setNewStatus(e.target.value)} data-testid="admin-status-select">
                  {ORDER_STATUSES.map(s => <option key={s} value={s}>{s.replace(/_/g,' ')}</option>)}
                </select>
                <input className="zx-input flex-1 min-w-[10rem]" placeholder="Note (optional)" value={note} onChange={e=>setNote(e.target.value)} />
                <button className="zx-btn-primary" onClick={updateStatus} data-testid="admin-update-status-btn">Update</button>
              </div>
            </div>

            <div className="mt-4">
              <div className="font-semibold text-sm mb-2">Timeline</div>
              <ol className="relative border-l border-[#E5E7EB] pl-4 space-y-2">
                {(sel.history||[]).map((h,i)=>(
                  <li key={i} className="text-sm">
                    <div className="absolute -left-1.5 w-3 h-3 bg-[#00509E] rounded-sm"></div>
                    <div className="text-[#0A1128] font-semibold">{h.to_status.replace(/_/g,' ')}</div>
                    <div className="text-xs text-[#6B7280]">{new Date(h.timestamp).toLocaleString()} — {h.actor_email}</div>
                    {h.note && <div className="text-xs text-[#4B5563]">{h.note}</div>}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Payments() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("pending_verification"); // or "unpaid"
  const load = async () => {
    if (tab === "pending_verification") {
      const { data } = await api.get("/orders/admin/all?payment_status=PENDING_VERIFICATION");
      setItems(data);
    } else {
      const { data } = await api.get("/admin/payments/pending");
      setItems(data);
    }
  };
  useEffect(()=>{ load(); /* eslint-disable-next-line */ }, [tab]);

  const remindAll = async (force=false) => {
    if (!confirm(`Send a payment reminder email to every customer with an unpaid order?${force?"\n(force=true — ignores 24h cooldown)":"\n(orders reminded in the last 24h will be skipped)"}`)) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/admin/payments/remind-all${force?"?force=true":""}`);
      toast.success(`Sent ${data.sent} reminder${data.sent===1?"":"s"} · skipped ${data.skipped} · matched ${data.matched}`);
      load();
    } catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const remindOne = async (id) => {
    setBusy(true);
    try {
      await api.post(`/admin/payments/${id}/remind`);
      toast.success("Reminder sent"); load();
    } catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Payments</h2>
        {tab === "unpaid" && (
          <div className="flex gap-2">
            <button className="zx-btn-outline" onClick={()=>remindAll(false)} disabled={busy} data-testid="remind-all-btn"><Bell size={14}/>{busy?"Sending…":"Send reminders to all"}</button>
            <button className="zx-btn-primary" onClick={()=>remindAll(true)} disabled={busy} data-testid="remind-all-force-btn">Force resend</button>
          </div>
        )}
      </div>
      <div className="mt-3 flex gap-1 border-b border-[#E5E7EB]">
        <button onClick={()=>setTab("pending_verification")} className={`px-3 py-2 text-sm border-b-2 ${tab==="pending_verification"?"border-[#00509E] text-[#00509E] font-semibold":"border-transparent text-[#0A1128]"}`} data-testid="payments-tab-pending">Pending Verification</button>
        <button onClick={()=>setTab("unpaid")} className={`px-3 py-2 text-sm border-b-2 ${tab==="unpaid"?"border-[#00509E] text-[#00509E] font-semibold":"border-transparent text-[#0A1128]"}`} data-testid="payments-tab-unpaid">Awaiting Payment</button>
      </div>
      <div className="overflow-x-auto mt-4"><table className="zx-table" data-testid="admin-payments-table">
        <thead>{tab==="pending_verification" ? (
          <tr><th>Order</th><th>Customer</th><th>Amount</th><th>Status</th></tr>
        ) : (
          <tr><th>Order</th><th>Customer</th><th>Amount</th><th>Status</th><th>Last Reminded</th><th></th></tr>
        )}</thead>
        <tbody>
          {items.map(o => tab==="pending_verification" ? (
            <tr key={o.id}><td>{o.order_number}</td><td>{o.customer_name} <div className="text-xs text-[#6B7280]">{o.customer_email}</div></td><td>₹{Number(o.amount).toLocaleString('en-IN')}</td><td><StatusBadge status={o.payment_status}/></td></tr>
          ) : (
            <tr key={o.id}>
              <td>{o.order_number}</td>
              <td>{o.customer_name} <div className="text-xs text-[#6B7280]">{o.customer_email}</div></td>
              <td>₹{Number(o.amount).toLocaleString('en-IN')}</td>
              <td><StatusBadge status={o.payment_status}/></td>
              <td className="text-xs">{o.last_reminded_at ? new Date(o.last_reminded_at).toLocaleString() : "—"}</td>
              <td><button onClick={()=>remindOne(o.id)} className="zx-link text-sm" data-testid={`remind-${o.order_number}`}>Send reminder</button></td>
            </tr>
          ))}
          {items.length===0 && <tr><td colSpan={tab==="pending_verification"?4:6} className="py-6 text-center text-[#6B7280]">Nothing here.</td></tr>}
        </tbody>
      </table></div>
    </div>
  );
}

function ServicesAdmin() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ name:"", slug:"", description:"", price:0, category:"General", active:true });
  const load = () => api.get("/services?active_only=false").then(r=>setItems(r.data));
  useEffect(()=>{ load(); },[]);
  const create = async (e) => { e.preventDefault();
    try { await api.post("/services", { ...form, price: Number(form.price) }); toast.success("Service added"); setForm({ name:"", slug:"", description:"", price:0, category:"General", active:true }); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const toggle = async (s) => { await api.put(`/services/${s.id}`, { active: !s.active }); load(); };
  const del = async (s) => { if(confirm(`Delete ${s.name}?`)){ await api.delete(`/services/${s.id}`); load(); } };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Services</h2>
      <form onSubmit={create} className="zx-card mt-4 grid grid-cols-1 md:grid-cols-6 gap-2" data-testid="new-service-form">
        <input className="zx-input md:col-span-2" placeholder="Name" value={form.name} onChange={e=>setForm({...form, name:e.target.value})} required />
        <input className="zx-input" placeholder="slug-key" value={form.slug} onChange={e=>setForm({...form, slug:e.target.value})} required />
        <input className="zx-input" placeholder="Category" value={form.category} onChange={e=>setForm({...form, category:e.target.value})} />
        <input type="number" className="zx-input" placeholder="Price" value={form.price} onChange={e=>setForm({...form, price:e.target.value})} required />
        <button className="zx-btn-primary" data-testid="add-service-btn">Add</button>
        <textarea rows={2} className="zx-input md:col-span-6" placeholder="Description" value={form.description} onChange={e=>setForm({...form, description:e.target.value})} required />
      </form>
      <div className="overflow-x-auto mt-4"><table className="zx-table"><thead><tr><th>Name</th><th>Slug</th><th>Price</th><th>Active</th><th></th></tr></thead><tbody>
        {items.map(s=>(<tr key={s.id}><td>{s.name}</td><td>{s.slug}</td><td>₹{s.price}</td><td>{s.active?"Yes":"No"}</td><td className="flex gap-2"><button className="zx-link text-sm" onClick={()=>toggle(s)}>{s.active?"Disable":"Enable"}</button><button className="zx-link text-sm" onClick={()=>del(s)}>Delete</button></td></tr>))}
      </tbody></table></div>
    </div>
  );
}

function Content() {
  const [content, setContent] = useState({});
  const [key, setKey] = useState("hero");
  const [json, setJson] = useState("");
  const load = () => api.get("/content").then(r=>setContent(r.data||{}));
  useEffect(()=>{ load(); },[]);
  useEffect(()=>{ setJson(JSON.stringify(content[key] || {}, null, 2)); }, [key, content]);
  const save = async () => {
    try { const val = JSON.parse(json); await api.put("/admin/content", { key, value: val }); toast.success("Content updated"); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Invalid JSON"); }
  };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Website Content</h2>
      <p className="text-sm text-[#6B7280]">Edit the site's public content. Each key holds a JSON object.</p>
      <div className="mt-4 flex gap-2 flex-wrap">
        {["hero","about","programmer","udyam","contact","why","announcement"].map(k => (
          <button key={k} onClick={()=>setKey(k)} className={`zx-badge ${key===k?"zx-badge-blue":"zx-badge-gray"}`} data-testid={`content-key-${k}`}>{k}</button>
        ))}
      </div>
      <textarea rows={16} className="zx-input mt-3 font-mono text-xs" value={json} onChange={e=>setJson(e.target.value)} data-testid="content-json"></textarea>
      <button className="zx-btn-primary mt-3" onClick={save} data-testid="content-save-btn">Save {key}</button>
    </div>
  );
}

function AdminNotifs() {
  const [form, setForm] = useState({ user_id: "", title: "", body: "" });
  const [users, setUsers] = useState([]);
  useEffect(()=>{ api.get("/admin/customers").then(r=>setUsers(r.data)); },[]);
  const send = async (e) => {
    e.preventDefault();
    try { await api.post("/admin/notifications", { ...form, user_id: form.user_id || null }); toast.success("Sent"); setForm({user_id:"", title:"", body:""}); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Send Notification</h2>
      <form onSubmit={send} className="zx-card mt-4 space-y-3 max-w-lg" data-testid="admin-notif-form">
        <select className="zx-input" value={form.user_id} onChange={e=>setForm({...form, user_id: e.target.value})}>
          <option value="">Broadcast to all customers</option>
          {users.map(u => <option key={u.id} value={u.id}>{u.name} — {u.email}</option>)}
        </select>
        <input className="zx-input" placeholder="Title" value={form.title} onChange={e=>setForm({...form, title:e.target.value})} required />
        <textarea rows={4} className="zx-input" placeholder="Body" value={form.body} onChange={e=>setForm({...form, body:e.target.value})} required />
        <button className="zx-btn-primary" data-testid="send-notif-btn">Send</button>
      </form>
    </div>
  );
}


function SupportTicketsAdmin() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.get(`/support/admin/tickets${status || priority ? `?${new URLSearchParams({...(status?{status}:{}),...(priority?{priority}:{})}).toString()}` : ""}`).then(r=>setItems(r.data));
  useEffect(()=>{ load(); }, [status, priority]);
  const update = async (extra={}) => {
    if (!selected) return;
    setBusy(true);
    try { const {data}=await api.put(`/support/admin/tickets/${selected.id}`, extra); setSelected(data); setReply(""); load(); toast.success("Ticket updated"); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return <div>
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-serif text-2xl font-bold text-[#0A1128]">Support Tickets</h2>
      <div className="flex gap-2"><select className="zx-input" value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option><option value="open">Open</option><option value="in_progress">In progress</option><option value="waiting_customer">Waiting customer</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select>
      <select className="zx-input" value={priority} onChange={e=>setPriority(e.target.value)}><option value="">All priorities</option><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></div>
    </div>
    <div className="overflow-x-auto mt-4"><table className="zx-table"><thead><tr><th>Ticket</th><th>Customer</th><th>Subject</th><th>Priority</th><th>Status</th><th>Updated</th></tr></thead><tbody>
      {items.map(t=><tr key={t.id} onClick={()=>setSelected(t)} className="cursor-pointer"><td>{t.ticket_number}</td><td>{t.customer_name}<div className="text-xs text-[#6B7280]">{t.customer_email}</div></td><td>{t.subject}</td><td>{t.priority}</td><td>{t.status.replace(/_/g," ")}</td><td className="text-xs">{new Date(t.updated_at).toLocaleString()}</td></tr>)}
      {items.length===0 && <tr><td colSpan="6" className="text-center py-6 text-[#6B7280]">No support tickets.</td></tr>}
    </tbody></table></div>
    {selected && <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40" onClick={()=>setSelected(null)}>
      <div className="bg-white max-w-3xl w-full p-6 border max-h-[90vh] overflow-y-auto" onClick={e=>e.stopPropagation()}>
        <div className="flex justify-between"><div><div className="text-xs uppercase text-[#00509E]">{selected.ticket_number}</div><h3 className="font-serif text-xl font-bold">{selected.subject}</h3><div className="text-xs text-[#6B7280]">{selected.customer_name} · {selected.customer_email}</div></div><button onClick={()=>setSelected(null)}>✕</button></div>
        <div className="mt-4 text-sm whitespace-pre-wrap">{selected.message}</div>
        <div className="mt-4 flex flex-wrap gap-2"><select className="zx-input max-w-xs" value={selected.status} onChange={e=>setSelected({...selected,status:e.target.value})}><option value="open">Open</option><option value="in_progress">In progress</option><option value="waiting_customer">Waiting customer</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select><select className="zx-input max-w-xs" value={selected.priority} onChange={e=>setSelected({...selected,priority:e.target.value})}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select><button className="zx-btn-primary" disabled={busy} onClick={()=>update({status:selected.status,priority:selected.priority})}>Save</button></div>
        <div className="mt-5 space-y-2">{(selected.replies||[]).map(r=><div key={r.id} className="border border-[#E5E7EB] p-3 text-sm"><div className="text-xs font-semibold text-[#6B7280]">{r.role === "admin" ? "Admin" : selected.customer_name} · {new Date(r.created_at).toLocaleString()}</div><div className="mt-1 whitespace-pre-wrap">{r.message}</div></div>)}</div>
        {!["closed"].includes(selected.status) && <div className="mt-4 flex gap-2"><textarea className="zx-input" rows={3} placeholder="Reply to customer" value={reply} onChange={e=>setReply(e.target.value)} /><button className="zx-btn-primary self-end" disabled={busy || !reply.trim()} onClick={()=>update({reply, status:"in_progress"})}>Reply</button></div>}
      </div>
    </div>}
  </div>;
}

function AuditLogs() {
  const [items, setItems] = useState([]);
  useEffect(()=>{ api.get("/admin/audit-logs").then(r=>setItems(r.data)); },[]);
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Audit Logs</h2>
      <div className="overflow-x-auto mt-4"><table className="zx-table" data-testid="audit-table"><thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Target</th></tr></thead><tbody>
        {items.map(a => (
          <tr key={a.id}><td className="text-xs">{new Date(a.timestamp).toLocaleString()}</td><td className="text-xs">{a.actor_email||"system"}</td><td>{a.action}</td><td className="text-xs">{a.target_type}/{a.target_id||"—"}</td></tr>
        ))}
      </tbody></table></div>
    </div>
  );
}

function Reports() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const load = () => api.get(`/reports/monthly?days=${days}`).then(r=>setData(r.data));
  useEffect(()=>{ load(); /* eslint-disable-next-line */ }, [days]);
  const sendNow = async () => {
    setBusy(true);
    try { await api.post("/reports/monthly/send"); toast.success("Report email queued to admin inbox"); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const money = (v) => `₹${Number(v||0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Reports</h2>
        <div className="flex gap-2 items-center">
          <select className="zx-input" value={days} onChange={e=>setDays(Number(e.target.value))} data-testid="reports-period">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button className="zx-btn-primary" onClick={sendNow} disabled={busy} data-testid="reports-send-now">
            {busy ? "Queuing…" : "Email me the report now"}
          </button>
        </div>
      </div>
      {!data ? <div className="text-sm text-[#6B7280] mt-4">Loading…</div> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
            {[
              { l: "Revenue (verified)", v: money(data.revenue) },
              { l: "Verified orders", v: data.verified_orders },
              { l: "Pending payments", v: data.pending_payments },
              { l: "Completed", v: data.completed_orders },
              { l: "New enquiries", v: data.new_enquiries },
              { l: "New customers", v: data.new_customers },
            ].map(c => (
              <div key={c.l} className="zx-card" data-testid={`report-stat-${c.l.toLowerCase().replace(/[^a-z]+/g,'-')}`}>
                <div className="text-xs uppercase text-[#6B7280] font-semibold">{c.l}</div>
                <div className="font-serif text-2xl font-bold mt-1 text-[#0A1128]">{c.v}</div>
              </div>
            ))}
          </div>
          <div className="text-xs text-[#6B7280] mt-2">
            Period: {data.period_start?.slice(0,10)} → {data.period_end?.slice(0,10)}
            {data.revenue_change_pct != null && (
              <> · vs previous {data.period_days} days: <b className={data.revenue_change_pct>=0?"text-[#146C2E]":"text-[#A11B1B]"}>{data.revenue_change_pct.toFixed(1)}%</b></>
            )}
          </div>
          <div className="mt-6">
            <div className="text-sm font-semibold text-[#0A1128] mb-2">Top services</div>
            <div className="overflow-x-auto"><table className="zx-table"><thead><tr><th>Service</th><th className="text-right">Orders</th><th className="text-right">Revenue</th></tr></thead>
              <tbody>
                {data.top_services.map(s => (
                  <tr key={s.name}><td>{s.name}</td><td className="text-right">{s.count}</td><td className="text-right">{money(s.revenue)}</td></tr>
                ))}
                {data.top_services.length===0 && <tr><td colSpan="3" className="text-center py-4 text-[#6B7280]">No verified orders in this period.</td></tr>}
              </tbody></table></div>
          </div>
          <div className="text-xs text-[#6B7280] mt-6 border-t border-[#E5E7EB] pt-3">
            <b>Scheduled delivery:</b> A monthly report is emailed automatically to the admin on the 1st of each month at 09:00 IST.
          </div>
        </>
      )}
    </div>
  );
}

export default function AdminDashboard() {
  const { user, logout } = useAuth();
  const links = [
    { to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/admin/customers", label: "Customers", icon: Users },
    { to: "/admin/enquiries", label: "Enquiries", icon: FileText },
    { to: "/admin/support", label: "Support Tickets", icon: MessageCircle },
    { to: "/admin/orders", label: "Orders", icon: ShoppingBag },
    { to: "/admin/payments", label: "Payments", icon: CreditCard },
    { to: "/admin/services", label: "Services", icon: Server },
    { to: "/admin/notifications", label: "Notifications", icon: Bell },
    { to: "/admin/content", label: "Website Content", icon: Settings },
    { to: "/admin/reports", label: "Reports", icon: BarChart3 },
    { to: "/admin/audit", label: "Audit Logs", icon: ClipboardList },
  ];
  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#F8F9FA]">
      <aside className="zx-sidebar md:w-[240px] md:min-h-screen" data-testid="admin-sidebar">
        <div className="px-4 py-4 border-b border-[#1E2A44]">
          <div className="font-serif text-lg font-bold text-white">ZEROAXIS</div>
          <div className="text-xs text-[#94A3B8]">Admin Panel</div>
        </div>
        <nav className="flex md:flex-col flex-wrap py-2">
          {links.map(l => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({isActive})=>isActive?"active":""} data-testid={`admin-nav-${l.label.replace(/\s+/g,'-').toLowerCase()}`}>
              <l.icon size={16} /> {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-[#1E2A44] text-xs text-[#94A3B8] mt-auto">
          <div>{user?.email}</div>
          <button onClick={logout} className="mt-2 text-white underline" data-testid="admin-logout-btn">Logout</button>
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        <div className="border-b border-[#E5E7EB] bg-white px-6 py-3">
          <div className="text-sm text-[#4B5563]">Signed in as <b className="text-[#0A1128]">{user?.name}</b> ({user?.email})</div>
        </div>
        <div className="p-6">
          <Routes>
            <Route index element={<Dash />} />
            <Route path="customers" element={<Customers />} />
            <Route path="enquiries" element={<Enquiries />} />
            <Route path="support" element={<SupportTicketsAdmin />} />
            <Route path="orders" element={<Orders />} />
            <Route path="payments" element={<Payments />} />
            <Route path="services" element={<ServicesAdmin />} />
            <Route path="notifications" element={<AdminNotifs />} />
            <Route path="content" element={<Content />} />
            <Route path="reports" element={<Reports />} />
            <Route path="audit" element={<AuditLogs />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
