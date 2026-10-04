import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { LayoutDashboard, FileText, ShoppingBag, MapPin, Bell, UserCircle, Download, Upload, Paperclip, Trash2 } from "lucide-react";
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
      const a = document.createElement("a");
      a.href = url; a.download = f.original_name; document.body.appendChild(a); a.click();
      a.remove(); setTimeout(()=>URL.revokeObjectURL(url), 2000);
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
        <label className="zx-btn-outline cursor-pointer text-xs" data-testid={`upload-file-${parentType}-${parentId}`}>
          <Upload size={12}/> {busy ? "Uploading…" : "Upload"}
          <input type="file" className="hidden" onChange={upload} disabled={busy} />
        </label>
      </div>
      <div className="mt-2 text-xs text-[#6B7280]">Allowed: PDF, images, docs, spreadsheets, zip. Max 10 MB.</div>
      <div className="mt-2 space-y-1.5">
        {files.map(f => (
          <div key={f.id} className="flex items-center justify-between border border-[#E5E7EB] px-3 py-1.5 text-sm bg-white">
            <div className="min-w-0">
              <div className="truncate text-[#0A1128]">{f.original_name}</div>
              <div className="text-xs text-[#6B7280]">{bytesHuman(f.size)} · {new Date(f.created_at).toLocaleString()}</div>
            </div>
            <div className="flex gap-2 shrink-0">
              <button onClick={()=>download(f)} className="zx-link text-xs flex items-center gap-1" data-testid={`download-file-${f.id}`}><Download size={12}/>Download</button>
              <button onClick={()=>remove(f)} className="text-[#A11B1B] text-xs flex items-center gap-1" data-testid={`delete-file-${f.id}`}><Trash2 size={12}/></button>
            </div>
          </div>
        ))}
        {files.length===0 && <div className="text-xs text-[#6B7280]">No attachments yet.</div>}
      </div>
    </div>
  );
}

async function downloadInvoice(orderId, orderNumber) {
  try {
    const resp = await api.get(`/orders/${orderId}/invoice.pdf`, { responseType: "blob" });
    const url = URL.createObjectURL(resp.data);
    const a = document.createElement("a");
    a.href = url; a.download = `invoice-${orderNumber}.pdf`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url), 2000);
  } catch(e){ toast.error("Invoice download failed"); }
}

function StatusBadge({ status, type = "order" }) {
  const map = {
    UNPAID: "gray", PAYMENT_SUBMITTED: "amber", PENDING_VERIFICATION: "amber",
    PAYMENT_VERIFIED: "green", PAYMENT_REJECTED: "red", REFUNDED: "gray",
    CREATED: "blue", WORK_STARTED: "blue", IN_PROGRESS: "blue",
    READY_FOR_DELIVERY: "amber", COMPLETED: "green", CANCELLED: "red",
  };
  return <span className={`zx-badge zx-badge-${map[status] || "gray"}`}>{String(status).replace(/_/g,' ')}</span>;
}

function Overview() {
  const [orders, setOrders] = useState([]);
  const [enq, setEnq] = useState([]);
  const [notifs, setNotifs] = useState([]);
  useEffect(() => {
    api.get("/orders/mine").then(r => setOrders(r.data));
    api.get("/enquiries/mine").then(r => setEnq(r.data));
    api.get("/notifications").then(r => setNotifs(r.data));
  }, []);
  const active = orders.filter(o => !["COMPLETED","CANCELLED"].includes(o.order_status));
  const pending = orders.filter(o => o.payment_status === "PENDING_VERIFICATION");
  const completed = orders.filter(o => o.order_status === "COMPLETED");
  const unread = notifs.filter(n => !n.read).length;
  const cards = [
    { label: "Active orders", value: active.length },
    { label: "Pending payment", value: pending.length },
    { label: "Completed orders", value: completed.length },
    { label: "Unread notifications", value: unread },
  ];
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Overview</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
        {cards.map(c => (
          <div key={c.label} className="zx-card" data-testid={`stat-${c.label.replace(/\s+/g,'-').toLowerCase()}`}>
            <div className="text-xs uppercase text-[#6B7280] font-semibold">{c.label}</div>
            <div className="font-serif text-3xl font-bold mt-1 text-[#0A1128]">{c.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-8">
        <div className="text-sm font-semibold text-[#0A1128] mb-2">Recent enquiries</div>
        <div className="overflow-x-auto"><table className="zx-table"><thead><tr><th>Number</th><th>Service</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>{enq.slice(0,5).map(e => (
            <tr key={e.id}><td>{e.enquiry_number}</td><td>{e.service_name}</td><td><StatusBadge status={e.status} /></td><td>{new Date(e.created_at).toLocaleDateString()}</td></tr>
          ))}
          {enq.length===0 && <tr><td colSpan="4" className="text-center text-[#6B7280] py-6">No enquiries yet.</td></tr>}
          </tbody></table></div>
      </div>
    </div>
  );
}

function MyEnquiries() {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  useEffect(()=>{ api.get("/enquiries/mine").then(r=>setItems(r.data)); },[]);
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">My Enquiries</h2>
      <div className="overflow-x-auto mt-4"><table className="zx-table" data-testid="my-enquiries-table"><thead><tr><th>Number</th><th>Service</th><th>Requirement</th><th>Status</th><th>Response</th><th></th></tr></thead><tbody>
        {items.map(e => (
          <tr key={e.id}>
            <td>{e.enquiry_number}</td><td>{e.service_name}</td>
            <td className="max-w-md">{e.requirement}</td>
            <td><StatusBadge status={e.status} /></td>
            <td className="text-xs text-[#4B5563] max-w-md">{e.admin_response || "—"}</td>
            <td><button className="zx-link text-sm" onClick={()=>setSel(e)} data-testid={`view-enquiry-${e.enquiry_number}`}>Attach files</button></td>
          </tr>
        ))}
        {items.length===0 && <tr><td colSpan="6" className="text-center text-[#6B7280] py-6">No enquiries yet.</td></tr>}
      </tbody></table></div>
      {sel && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40" onClick={()=>setSel(null)}>
          <div className="bg-white max-w-xl w-full p-6 border" onClick={e=>e.stopPropagation()}>
            <div className="flex justify-between items-start">
              <div>
                <div className="text-xs uppercase text-[#00509E] font-semibold">Enquiry</div>
                <div className="font-serif text-xl font-bold">{sel.enquiry_number}</div>
                <div className="text-sm text-[#4B5563]">{sel.service_name}</div>
              </div>
              <button onClick={()=>setSel(null)}>✕</button>
            </div>
            <div className="mt-2 text-sm"><b>Requirement:</b> {sel.requirement}</div>
            {sel.admin_response && <div className="mt-1 text-sm"><b>Response:</b> {sel.admin_response}</div>}
            <FileAttachments parentType="enquiry" parentId={sel.id} />
            <MessagesThread parentType="enquiry" parentId={sel.id} />
          </div>
        </div>
      )}
    </div>
  );
}

function NewOrder({ onCreated }) {
  const [services, setServices] = useState([]);
  const [form, setForm] = useState({ service_id: "", requirement: "", notes: "" });
  const [busy, setBusy] = useState(false);
  useEffect(()=>{ api.get("/services").then(r=>setServices(r.data)); },[]);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      const { data } = await api.post("/orders", form);
      toast.success(`Order ${data.order_number} created`);
      setForm({ service_id:"", requirement:"", notes:"" });
      onCreated && onCreated();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="zx-card space-y-3" data-testid="new-order-form">
      <div className="font-semibold text-[#0A1128]">Place a new order</div>
      <div><label className="zx-label">Service</label>
        <select required className="zx-input" value={form.service_id} onChange={e=>setForm({...form, service_id: e.target.value})} data-testid="new-order-service">
          <option value="">Select a service</option>
          {services.map(s => <option key={s.id} value={s.id}>{s.name} — ₹{s.price}</option>)}
        </select>
      </div>
      <div><label className="zx-label">Requirement</label><input required className="zx-input" value={form.requirement} onChange={e=>setForm({...form, requirement: e.target.value})} data-testid="new-order-requirement" /></div>
      <div><label className="zx-label">Notes</label><textarea rows={3} className="zx-input" value={form.notes} onChange={e=>setForm({...form, notes: e.target.value})} data-testid="new-order-notes" /></div>
      <button disabled={busy} className="zx-btn-primary" data-testid="new-order-submit-btn">{busy?"Creating…":"Create Order"}</button>
    </form>
  );
}

function PaymentForm({ orderId, amount, onDone }) {
  const [form, setForm] = useState({ method: "UPI", reference: "", amount, note: "" });
  const [busy, setBusy] = useState(false);
  const [qr, setQr] = useState(null);
  useEffect(() => {
    api.get(`/orders/${orderId}/qr`).then(r => setQr(r.data)).catch(()=>setQr({data_url:null}));
  }, [orderId]);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      await api.post(`/orders/${orderId}/payment`, { ...form, amount: Number(form.amount) });
      toast.success("Payment submitted for verification"); onDone && onDone();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="space-y-2 mt-3" data-testid={`payment-form-${orderId}`}>
      {qr && qr.data_url ? (
        <div className="border border-[#E5E7EB] p-3 bg-[#F8F9FA] flex gap-3 items-start" data-testid={`payment-qr-${orderId}`}>
          <img src={qr.data_url} alt="Payment QR" className="w-32 h-32 object-contain bg-white border border-[#E5E7EB] p-1" />
          <div className="text-xs text-[#4B5563]">
            <div className="font-semibold text-[#0A1128] mb-1">Scan to pay</div>
            <div>Amount: <b>₹{Number(amount).toLocaleString('en-IN')}</b></div>
            {qr.label && <div className="mt-1">{qr.label}</div>}
            <div className="mt-2 text-[#6B7280]">After paying, enter the UPI/UTR reference below and submit for verification.</div>
          </div>
        </div>
      ) : (
        <div className="text-xs text-[#6B7280] border border-dashed border-[#E5E7EB] p-2">
          Payment QR is not yet available for this order. Please contact admin for payment details or submit your reference after paying via the shared method.
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <select className="zx-input" value={form.method} onChange={e=>setForm({...form, method: e.target.value})}>
          <option>UPI</option><option>Bank Transfer</option><option>Cash</option><option>Other</option>
        </select>
        <input className="zx-input" placeholder="Reference / UTR" value={form.reference} onChange={e=>setForm({...form, reference: e.target.value})} required data-testid={`payment-reference-${orderId}`} />
      </div>
      <input type="number" className="zx-input" placeholder="Amount" value={form.amount} onChange={e=>setForm({...form, amount: e.target.value})} required />
      <textarea rows={2} className="zx-input" placeholder="Note (optional)" value={form.note} onChange={e=>setForm({...form, note: e.target.value})}></textarea>
      <button disabled={busy} className="zx-btn-primary" data-testid={`payment-submit-${orderId}`}>{busy?"Submitting…":"Submit Payment"}</button>
    </form>
  );
}

function MyOrders() {
  const [orders, setOrders] = useState([]);
  const [selected, setSelected] = useState(null);
  const load = () => api.get("/orders/mine").then(r=>setOrders(r.data));
  useEffect(()=>{ load(); },[]);
  const openDetail = async (id) => {
    const { data } = await api.get(`/orders/${id}`); setSelected(data);
  };
  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="font-serif text-2xl font-bold text-[#0A1128]">My Orders</h2>
      </div>
      <NewOrder onCreated={load} />
      <div className="overflow-x-auto mt-6"><table className="zx-table" data-testid="my-orders-table"><thead><tr><th>Order</th><th>Service</th><th>Amount</th><th>Payment</th><th>Status</th><th></th></tr></thead><tbody>
        {orders.map(o => (
          <tr key={o.id}>
            <td>{o.order_number}</td>
            <td>{o.service_name}</td>
            <td>₹{Number(o.amount).toLocaleString('en-IN')}</td>
            <td><StatusBadge status={o.payment_status} /></td>
            <td><StatusBadge status={o.order_status} /></td>
            <td><button onClick={()=>openDetail(o.id)} className="zx-link text-sm" data-testid={`view-order-${o.order_number}`}>View</button></td>
          </tr>
        ))}
        {orders.length===0 && <tr><td colSpan="6" className="text-center text-[#6B7280] py-6">No orders yet.</td></tr>}
      </tbody></table></div>

      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40" onClick={()=>setSelected(null)}>
          <div className="bg-white max-w-2xl w-full p-6 border border-[#E5E7EB]" onClick={e=>e.stopPropagation()} data-testid="order-detail-modal">
            <div className="flex justify-between items-start">
              <div>
                <div className="text-xs uppercase text-[#00509E] font-semibold">Order</div>
                <div className="font-serif text-xl font-bold text-[#0A1128]">{selected.order_number}</div>
                <div className="text-sm text-[#4B5563]">{selected.service_name}</div>
              </div>
              <button onClick={()=>setSelected(null)} className="text-[#4B5563]">✕</button>
            </div>
            <div className="mt-3 flex gap-2 flex-wrap">
              <StatusBadge status={selected.order_status} />
              <span className="zx-badge zx-badge-gray">Payment: {selected.payment_status}</span>
            </div>
            <div className="mt-4 text-sm"><b>Amount:</b> ₹{Number(selected.amount).toLocaleString('en-IN')}</div>
            <div className="text-sm mt-1"><b>Requirement:</b> {selected.requirement}</div>

            {selected.payment_status === "PAYMENT_VERIFIED" && (
              <div className="mt-3">
                <button onClick={()=>downloadInvoice(selected.id, selected.order_number)} className="zx-btn-primary" data-testid={`invoice-download-${selected.order_number}`}>
                  <Download size={14}/> Download Invoice (PDF)
                </button>
              </div>
            )}

            <FileAttachments parentType="order" parentId={selected.id} />
            <MessagesThread parentType="order" parentId={selected.id} />

            {["UNPAID","PAYMENT_REJECTED"].includes(selected.payment_status) && (
              <div className="mt-4">
                <div className="font-semibold text-sm">Submit Payment</div>
                <PaymentForm orderId={selected.id} amount={selected.amount} onDone={async()=>{ await load(); openDetail(selected.id); }} />
              </div>
            )}

            <div className="mt-4">
              <div className="font-semibold text-sm mb-2">Status Timeline</div>
              <ol className="relative border-l border-[#E5E7EB] pl-4 space-y-3">
                {(selected.history||[]).map((h,i)=>(
                  <li key={i} className="text-sm">
                    <div className="absolute -left-1.5 w-3 h-3 bg-[#00509E] rounded-sm"></div>
                    <div className="text-[#0A1128] font-semibold">{h.to_status.replace(/_/g,' ')}</div>
                    <div className="text-xs text-[#6B7280]">{new Date(h.timestamp).toLocaleString()}</div>
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

function Notifications() {
  const [items, setItems] = useState([]);
  const load = () => api.get("/notifications").then(r=>setItems(r.data));
  useEffect(()=>{ load(); },[]);
  const markRead = async (id) => { await api.post(`/notifications/${id}/read`); load(); };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Notifications</h2>
      <div className="mt-4 space-y-2">
        {items.map(n => (
          <div key={n.id} className={`zx-card flex justify-between gap-3 ${!n.read ? "border-l-2 border-l-[#00509E]" : ""}`} data-testid={`notif-${n.id}`}>
            <div>
              <div className="font-semibold text-[#0A1128]">{n.title}</div>
              <div className="text-sm text-[#4B5563] mt-0.5">{n.body}</div>
              <div className="text-xs text-[#6B7280] mt-1">{new Date(n.created_at).toLocaleString()}</div>
            </div>
            {!n.read && <button onClick={()=>markRead(n.id)} className="zx-link text-sm h-fit" data-testid={`mark-read-${n.id}`}>Mark read</button>}
          </div>
        ))}
        {items.length===0 && <div className="text-sm text-[#6B7280]">No notifications.</div>}
      </div>
    </div>
  );
}

function Profile() {
  const { user, refresh } = useAuth();
  const [form, setForm] = useState({ name: user?.name || "", phone: user?.phone || "", address: user?.address || "", company: user?.company || "" });
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try { await api.put("/users/me", form); await refresh(); toast.success("Profile updated"); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <div>
      <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Profile</h2>
      <form onSubmit={submit} className="zx-card mt-4 space-y-3 max-w-lg" data-testid="profile-form">
        <div><label className="zx-label">Name</label><input className="zx-input" value={form.name} onChange={e=>setForm({...form, name: e.target.value})} /></div>
        <div><label className="zx-label">Phone</label><input className="zx-input" value={form.phone||""} onChange={e=>setForm({...form, phone: e.target.value})} /></div>
        <div><label className="zx-label">Company</label><input className="zx-input" value={form.company||""} onChange={e=>setForm({...form, company: e.target.value})} /></div>
        <div><label className="zx-label">Address</label><textarea rows={3} className="zx-input" value={form.address||""} onChange={e=>setForm({...form, address: e.target.value})} /></div>
        <div className="text-sm text-[#6B7280]">Email: {user?.email} (cannot be changed)</div>
        <button disabled={busy} className="zx-btn-primary" data-testid="profile-save-btn">{busy?"Saving…":"Save"}</button>
      </form>

      <div className="zx-card mt-6 max-w-lg border-[#D1D5DB]">
        <div className="font-semibold text-[#0A1128]">Delete account</div>
        <p className="text-sm text-[#6B7280] mt-1">Permanently delete your customer login and account. Your existing orders and enquiries may remain as business records.</p>
        <button
          type="button"
          className="mt-4 border border-[#A11B1B] text-[#A11B1B] px-4 py-2 text-sm hover:bg-[#FEF2F2]"
          data-testid="delete-account-btn"
          onClick={async () => {
            if (!window.confirm("Delete your customer account permanently? You will be logged out and will need to create a new account to use customer login again.")) return;
            if (!window.confirm("This cannot be undone. Continue deleting your account?")) return;
            try {
              await api.delete("/auth/users/me");
              localStorage.removeItem("zx_token");
              toast.success("Your account has been deleted");
              setTimeout(() => { window.location.href = "/"; }, 500);
            } catch (e) {
              toast.error(formatApiErrorDetail(e.response?.data?.detail));
            }
          }}
        >Delete My Account</button>
      </div>
    </div>
  );
}

export default function CustomerDashboard() {
  const links = [
    { to: "/dashboard", label: "Overview", icon: LayoutDashboard, end: true },
    { to: "/dashboard/enquiries", label: "My Enquiries", icon: FileText },
    { to: "/dashboard/orders", label: "My Orders", icon: ShoppingBag },
    { to: "/dashboard/notifications", label: "Notifications", icon: Bell },
    { to: "/dashboard/profile", label: "Profile", icon: UserCircle },
  ];
  return (
    <div>
      <Header />
      <div className="container-page py-8 grid grid-cols-1 md:grid-cols-[220px_1fr] gap-8">
        <aside className="border border-[#E5E7EB] bg-white h-fit" data-testid="customer-sidebar">
          <div className="p-3 border-b border-[#E5E7EB] text-xs font-semibold uppercase text-[#6B7280]">Customer</div>
          <nav className="flex md:flex-col">
            {links.map(l => (
              <NavLink key={l.to} to={l.to} end={l.end} className={({isActive})=>`flex items-center gap-2 px-3 py-2 text-sm border-l-2 ${isActive?"border-l-[#00509E] text-[#00509E] bg-[#F8F9FA] font-semibold":"border-l-transparent text-[#0A1128] hover:bg-[#F8F9FA]"}`} data-testid={`cust-nav-${l.label.replace(/\s+/g,'-').toLowerCase()}`}>
                <l.icon size={16} /> {l.label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main>
          <Routes>
            <Route index element={<Overview />} />
            <Route path="enquiries" element={<MyEnquiries />} />
            <Route path="orders" element={<MyOrders />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="profile" element={<Profile />} />
          </Routes>
        </main>
      </div>
      <Footer />
    </div>
  );
}
