import { useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { LayoutDashboard, FileText, ShoppingBag, MapPin, Bell, UserCircle, Download, Upload, Paperclip, Trash2, MessageCircle } from "lucide-react";
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
  // Reload attachments when the parent record changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(()=>{ if(parentId) load(); }, [parentId, parentType]);
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
    UNPAID: "gray", PAYMENT_SUBMITTED: "amber", PENDING_VERIFICATION: "amber", PAYMENT_PENDING: "amber",
    PAYMENT_VERIFIED: "green", PAYMENT_REJECTED: "red", REFUNDED: "gray",
    CREATED: "blue", ORDER_RECEIVED: "amber", DEVELOPER_ASSIGNED: "blue", WORK_STARTED: "blue", IN_PROGRESS: "blue",
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
  const pending = orders.filter(o => ["PENDING_VERIFICATION", "PAYMENT_PENDING"].includes(o.payment_status));
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
      toast.success(`Order ${data.order_number} received. The team will review it before requesting payment.`);
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
  const [payment, setPayment] = useState(null);
  const [couponCode, setCouponCode] = useState("");
  const [couponBusy, setCouponBusy] = useState(false);
  const [couponResult, setCouponResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [visible, setVisible] = useState(true);
  const [manualMethod, setManualMethod] = useState("BANK_TRANSFER");
  const [manualReference, setManualReference] = useState("");
  const [manualFile, setManualFile] = useState(null);
  const [manualBusy, setManualBusy] = useState(false);
  const onDoneRef = useRef(onDone);

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    api.get("/orders/" + orderId + "/payment/status").then(({ data }) => {
      if (data.checkout) setPayment(data.checkout);
      if (data.status === "success") onDoneRef.current?.();
    }).catch(() => {});
  }, [orderId]);

  const applyCoupon = async () => {
    if (!couponCode.trim()) return toast.error("Enter a coupon code");
    setCouponBusy(true);
    try { const {data} = await api.post("/coupons/apply", {order_id:orderId, code:couponCode}); setCouponResult(data); toast.success("Coupon applied"); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setCouponBusy(false); }
  };

  const createCheckout = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/orders/" + orderId + "/payment/create");
      setPayment(data);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const submitManualPayment = async () => {
    if (!manualFile) return toast.error("Upload a payment receipt or proof first");
    setManualBusy(true);
    try {
      const fd = new FormData();
      fd.append("parent_type", "order");
      fd.append("parent_id", orderId);
      fd.append("note", "Manual payment proof");
      fd.append("file", manualFile);
      const uploaded = await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      await api.post("/orders/" + orderId + "/payment/manual-submit", {
        method: manualMethod, reference: manualReference, proof_file_id: uploaded.data.id,
      });
      toast.success("Payment proof submitted. It will remain pending until admin verification.");
      onDoneRef.current?.();
      setVisible(false);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setManualBusy(false); }
  };

  const checkStatus = async () => {
    setChecking(true);
    try {
      const { data } = await api.get("/orders/" + orderId + "/payment/status");
      if (data.status === "success") {
        toast.success("Payment confirmed");
        onDone && onDone();
      } else if (data.status === "expired") {
        setPayment(null);
        toast.error("Payment session expired. Please create a new payment session.");
      } else {
        toast.info("Payment is still awaiting confirmation");
      }
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setChecking(false); }
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[70] bg-[#0A1128]/55 backdrop-blur-sm flex items-center justify-center p-3 sm:p-5" onClick={e=>e.stopPropagation()} data-testid={"payment-form-" + orderId}>
      <section className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl border border-[#DCE3EC] bg-white shadow-2xl">
        <div className="border-b border-[#E5E7EB] bg-[#F8F9FA] px-5 py-4 flex items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6B7280]">ZEROAXIS · Secure payment</div>
            <h3 className="mt-1 font-serif text-xl font-bold text-[#0A1128]">Choose how to pay</h3>
            <p className="mt-1 text-xs text-[#6B7280]">Order {orderId}</p>
          </div>
          <button type="button" onClick={()=>setVisible(false)} className="rounded-full border border-[#DCE3EC] px-3 py-1.5 text-sm text-[#4B5563] hover:bg-white" aria-label="Close payment window">Close</button>
        </div>
        <div className="p-5 space-y-4">
          <div className="rounded-xl border border-[#DCE3EC] bg-[#F8F9FA] p-4 flex items-center justify-between gap-3">
            <div>
              <div className="text-xs text-[#6B7280]">Total amount</div>
              <div className="mt-1 text-sm font-semibold text-[#0A1128]">Order payment</div>
            </div>
            <div className="font-serif text-2xl font-bold text-[#0A1128]">₹{Number(payment?.payable_amount || couponResult?.payable_amount || amount).toLocaleString("en-IN")}</div>
          </div>

          {!payment && !couponResult && <div className="rounded-xl border border-[#DCE3EC] p-3 space-y-2"><label className="text-sm font-semibold text-[#0A1128]">Have a coupon code?</label><div className="flex gap-2"><input className="zx-input min-w-0" placeholder="Enter coupon code" value={couponCode} onChange={e=>setCouponCode(e.target.value.toUpperCase())} maxLength={32}/><button type="button" className="zx-btn-outline shrink-0" disabled={couponBusy} onClick={applyCoupon}>{couponBusy?"Applying…":"Apply"}</button></div></div>}
          {couponResult && <div className="rounded-xl border border-[#B7D8C2] bg-[#F3FAF5] p-3 text-sm"><b>Coupon {couponResult.coupon_code} applied</b><div className="flex justify-between"><span>Original</span><span>₹{Number(couponResult.base_amount).toLocaleString("en-IN")}</span></div><div className="flex justify-between"><span>Discount</span><span>−₹{Number(couponResult.discount_amount).toLocaleString("en-IN")}</span></div><div className="flex justify-between font-semibold border-t mt-1 pt-1"><span>Payable</span><span>₹{Number(couponResult.payable_amount).toLocaleString("en-IN")}</span></div></div>}
          {!payment ? (
            <div className="space-y-3">
              <div className="text-sm font-semibold text-[#0A1128]">UPI payment options</div>
              <div className="rounded-xl border border-[#E5E7EB] p-4 flex items-center gap-3">
                <div className="h-11 w-11 rounded-lg bg-[#F1F5F9] flex items-center justify-center text-[#00509E] font-bold">UPI</div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-[#0A1128]">Pay with any UPI app</div>
                  <div className="text-xs text-[#6B7280] mt-0.5">Google Pay, PhonePe, Paytm, BHIM and supported UPI apps</div>
                </div>
              </div>
              <button type="button" disabled={busy} onClick={createCheckout} className="zx-btn-primary w-full justify-center" data-testid={"payment-submit-" + orderId}>
                {busy ? "Loading payment options…" : "Continue with UPI"}
              </button>
              <p className="text-xs text-center text-[#6B7280]">Payment options will open here. No QR code is shown for direct UPI app payments.</p>
              <div className="border-t border-[#E5E7EB] pt-4 space-y-3">
                <div className="text-sm font-semibold text-[#0A1128]">Or record an offline payment</div>
                <p className="text-xs text-[#6B7280]">For cheque, cash or bank transfer. Upload a receipt or other payment evidence. This does not mark the order as paid until an admin verifies it.</p>
                <select className="zx-input" value={manualMethod} onChange={e=>setManualMethod(e.target.value)}>
                  <option value="BANK_TRANSFER">Bank transfer</option><option value="CHEQUE">Cheque</option><option value="CASH">Cash</option>
                </select>
                <input className="zx-input" maxLength={120} placeholder="Transaction / cheque / receipt reference (optional)" value={manualReference} onChange={e=>setManualReference(e.target.value)} />
                <input className="zx-input" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/*" onChange={e=>setManualFile(e.target.files?.[0] || null)} />
                <button type="button" disabled={manualBusy || !manualFile} onClick={submitManualPayment} className="zx-btn-outline w-full justify-center">
                  {manualBusy ? "Uploading proof…" : "Submit proof for verification"}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {payment.upi_intent && (
                <div className="rounded-xl border border-[#DCE3EC] p-4">
                  <div className="text-sm font-semibold text-[#0A1128]">Open your UPI app</div>
                  <p className="mt-1 text-xs leading-5 text-[#6B7280]">Continue to your preferred installed UPI app. The payment amount and merchant details will be passed through the UPI link.</p>
                  <a className="zx-btn-primary mt-3 w-full justify-center inline-flex" href={payment.upi_intent}>Choose UPI app</a>
                </div>
              )}
              {!payment.upi_intent && payment.checkout_url && (
                <a className="zx-btn-primary w-full justify-center inline-flex" href={payment.checkout_url} target="_blank" rel="noreferrer">Open secure payment options</a>
              )}
              {!payment.upi_intent && !payment.checkout_url && payment.qr_url && (
                <div className="rounded-xl border border-[#E5E7EB] p-4 text-center">
                  <div className="text-sm font-semibold text-[#0A1128] mb-3">Alternative QR payment</div>
                  <img src={payment.qr_url} alt="Payment QR fallback" className="mx-auto w-40 h-40 object-contain bg-white rounded-lg border border-[#E5E7EB] p-1" />
                </div>
              )}
              {payment.checkout_url && payment.upi_intent && <a className="zx-btn-outline w-full justify-center inline-flex" href={payment.checkout_url} target="_blank" rel="noreferrer">More payment methods</a>}
              <div className="rounded-xl border border-[#E5E7EB] p-3">
                <div className="text-xs text-[#6B7280]">Payment reference</div>
                <div className="mt-1 text-sm font-semibold text-[#0A1128] break-all">{payment.order_id}</div>
                <button type="button" className="zx-btn-outline mt-3 w-full justify-center" onClick={checkStatus} disabled={checking}>{checking ? "Checking payment…" : "I have paid — check status"}</button>
              </div>
              <p className="text-xs leading-5 text-[#6B7280]">Payment is marked complete only after verification from the payment provider.</p>
            </div>
          )}
        </div>
      </section>
    </div>
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
      <div className="mt-6 flex items-center justify-between gap-3">
        <div>
          <h3 className="font-serif text-lg font-bold text-[#0A1128]">Order history</h3>
          <p className="text-xs text-[#6B7280] mt-0.5">Track payments and project progress in one place</p>
        </div>
        <span className="zx-badge zx-badge-gray">{orders.length} total</span>
      </div>
      <div className="mt-3 space-y-3" data-testid="my-orders-table">
        {orders.map(o => (
          <article key={o.id} className="rounded-xl border border-[#DCE3EC] bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">{o.order_number}</div>
                <div className="mt-1 font-semibold text-[#0A1128]">{o.service_name}</div>
                <div className="mt-1 text-xs text-[#6B7280]">Tracking token: <span className="font-mono break-all">{o.tracking_number}</span></div>
              </div>
              <div className="font-serif text-xl font-bold text-[#0A1128]">₹{Number(o.amount).toLocaleString('en-IN')}</div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <StatusBadge status={o.payment_status} />
              <StatusBadge status={o.order_status} />
            </div>
            <div className="mt-3 flex justify-end border-t border-[#E5E7EB] pt-3">
              <button onClick={()=>openDetail(o.id)} className="zx-btn-outline text-sm" data-testid={`view-order-${o.order_number}`}>View order details</button>
            </div>
          </article>
        ))}
        {orders.length===0 && <div className="rounded-xl border border-dashed border-[#CBD5E1] bg-white py-10 text-center text-sm text-[#6B7280]">No orders yet. Your orders will appear here.</div>}
      </div>

      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40" onClick={()=>setSelected(null)}>
          <div className="bg-white max-w-2xl w-full p-6 border border-[#E5E7EB]" onClick={e=>e.stopPropagation()} data-testid="order-detail-modal">
            <div className="flex justify-between items-start">
              <div>
                <div className="text-xs uppercase text-[#00509E] font-semibold">Order</div>
                <div className="font-serif text-xl font-bold text-[#0A1128]">{selected.order_number}</div>
                <div className="text-sm text-[#4B5563]">{selected.service_name}</div>
                <div className="mt-1 text-xs text-[#6B7280]">Tracking token: <span className="font-mono break-all select-all">{selected.tracking_number}</span></div>
              </div>
              <button onClick={()=>setSelected(null)} className="text-[#4B5563]">✕</button>
            </div>
            <div className="mt-3 flex gap-2 flex-wrap">
              <StatusBadge status={selected.order_status} />
              <span className="zx-badge zx-badge-gray">Payment: {selected.payment_status}</span>
            </div>
            <div className="mt-4 text-sm"><b>Amount:</b> ₹{Number(selected.amount).toLocaleString('en-IN')}</div>
            <div className="text-sm mt-1"><b>Requirement:</b> {selected.requirement}</div>
            <div className="text-sm mt-1"><b>Assigned developer:</b> {selected.assigned_developer || "Awaiting admin assignment"}</div>
            <div className="text-sm mt-1"><b>Payment schedule:</b> {selected.payment_timing === "FIRST" ? "Before work starts" : selected.payment_timing === "LAST" ? "After work is completed" : "To be confirmed by admin"}</div>
            {!selected.payment_requested && <p className="mt-3 rounded-lg bg-[#F8F9FA] border border-[#E5E7EB] p-3 text-sm text-[#4B5563]">Order received. No payment is due yet. The administrator will assign a developer and request payment according to the agreed schedule.</p>}

            {selected.payment_status === "PAYMENT_VERIFIED" && (
              <div className="mt-3">
                <button onClick={()=>downloadInvoice(selected.id, selected.order_number)} className="zx-btn-primary" data-testid={`invoice-download-${selected.order_number}`}>
                  <Download size={14}/> Download Invoice (PDF)
                </button>
              </div>
            )}

            <FileAttachments parentType="order" parentId={selected.id} />
            <MessagesThread parentType="order" parentId={selected.id} />

            {selected.payment_requested && ["UNPAID","PAYMENT_REJECTED","PAYMENT_PENDING"].includes(selected.payment_status) && (
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


function SupportTickets() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({ subject: "", message: "", priority: "normal" });
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/support/tickets/mine").then(r => setItems(r.data));
  useEffect(() => { load(); }, []);
  const create = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      await api.post("/support/tickets", form);
      toast.success("Support ticket created");
      setForm({ subject: "", message: "", priority: "normal" }); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const sendReply = async () => {
    if (!reply.trim() || !selected) return;
    setBusy(true);
    try { const {data}=await api.post(`/support/tickets/${selected.id}/replies`, {message: reply}); setSelected(data); setReply(""); load(); }
    catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return <div>
    <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Support Tickets</h2>
    <form onSubmit={create} className="zx-card mt-4 space-y-3">
      <input className="zx-input" placeholder="Subject" maxLength={160} value={form.subject} onChange={e=>setForm({...form,subject:e.target.value})} required />
      <textarea className="zx-input" rows={4} placeholder="Describe your issue or question" maxLength={5000} value={form.message} onChange={e=>setForm({...form,message:e.target.value})} required />
      <div className="flex flex-wrap gap-2 items-center">
        <select className="zx-input max-w-xs" value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>
          <option value="low">Low priority</option><option value="normal">Normal priority</option><option value="high">High priority</option><option value="urgent">Urgent</option>
        </select>
        <button disabled={busy} className="zx-btn-primary">{busy ? "Submitting…" : "Create Ticket"}</button>
      </div>
    </form>
    <div className="mt-6 space-y-3">
      {items.map(t=><button key={t.id} onClick={()=>setSelected(t)} className="zx-card w-full text-left block hover:bg-[#F8F9FA]">
        <div className="flex flex-wrap justify-between gap-2"><span className="font-semibold">{t.ticket_number} · {t.subject}</span><span className="text-xs uppercase text-[#6B7280]">{t.status.replace(/_/g," ")}</span></div>
        <div className="text-xs text-[#6B7280] mt-1">Priority: {t.priority} · Updated {new Date(t.updated_at).toLocaleString()}</div>
      </button>)}
      {items.length===0 && <div className="text-sm text-[#6B7280]">No support tickets yet.</div>}
    </div>
    {selected && <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-40" onClick={()=>setSelected(null)}>
      <div className="bg-white max-w-2xl w-full p-5 border max-h-[90vh] overflow-y-auto" onClick={e=>e.stopPropagation()}>
        <div className="flex justify-between gap-3"><div><div className="text-xs uppercase text-[#00509E]">{selected.ticket_number}</div><h3 className="font-serif text-xl font-bold">{selected.subject}</h3></div><button onClick={()=>setSelected(null)}>✕</button></div>
        <div className="mt-3 text-sm whitespace-pre-wrap">{selected.message}</div>
        <div className="mt-4 space-y-2">{(selected.replies||[]).map(r=><div key={r.id} className="border border-[#E5E7EB] p-3 text-sm"><div className="text-xs font-semibold text-[#6B7280]">{r.role === "admin" ? "ZEROAXIS Support" : "You"} · {new Date(r.created_at).toLocaleString()}</div><div className="mt-1 whitespace-pre-wrap">{r.message}</div></div>)}</div>
        {!["closed","resolved"].includes(selected.status) && <div className="mt-4 flex gap-2"><textarea className="zx-input" rows={2} placeholder="Reply to support" value={reply} onChange={e=>setReply(e.target.value)} /><button disabled={busy} onClick={sendReply} className="zx-btn-primary self-end">Reply</button></div>}
      </div>
    </div>}
  </div>;
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
    { to: "/dashboard/support", label: "Support Tickets", icon: MessageCircle },
    { to: "/dashboard/notifications", label: "Notifications", icon: Bell },
    { to: "/dashboard/profile", label: "Profile", icon: UserCircle },
  ];
  return (
    <div>
      <Header />
      <div className="customer-dashboard container-page py-8 grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)] gap-8">
        <aside className="border border-[#E5E7EB] bg-white h-fit" data-testid="customer-sidebar">
          <div className="p-3 border-b border-[#E5E7EB] text-xs font-semibold uppercase text-[#6B7280]">Customer</div>
          <nav className="flex flex-col">
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
            <Route path="support" element={<SupportTickets />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="profile" element={<Profile />} />
          </Routes>
        </main>
      </div>
      <Footer />
    </div>
  );
}
