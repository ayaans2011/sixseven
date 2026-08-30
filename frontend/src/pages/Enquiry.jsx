import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import api, { formatApiErrorDetail } from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { Upload, Paperclip, Trash2, Download } from "lucide-react";

function bytesHuman(n) {
  if (!n && n !== 0) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n/1024).toFixed(1)} KB`;
  return `${(n/1024/1024).toFixed(2)} MB`;
}

function EnquiryAttachments({ enquiryId, canManage }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = () => api.get(`/files/list?parent_type=enquiry&parent_id=${enquiryId}`).then(r=>setFiles(r.data)).catch(()=>{});
  useEffect(()=>{ if(canManage) load(); /* eslint-disable-next-line */ }, [enquiryId, canManage]);
  const upload = async (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    if (f.size > 10 * 1024 * 1024) return toast.error("Max 10 MB");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("parent_type", "enquiry"); fd.append("parent_id", enquiryId); fd.append("file", f);
      await api.post("/files/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Attached"); load();
    } catch(e){ toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); e.target.value = ""; }
  };
  const download = async (f) => {
    const resp = await api.get(`/files/${f.id}/download`, { responseType: "blob" });
    const url = URL.createObjectURL(resp.data);
    const a = document.createElement("a"); a.href = url; a.download = f.original_name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url), 2000);
  };
  const remove = async (f) => {
    if (!confirm(`Remove ${f.original_name}?`)) return;
    await api.delete(`/files/${f.id}`); load();
  };
  if (!canManage) return null;
  return (
    <div className="mt-4">
      <div className="flex items-center justify-between">
        <div className="font-semibold text-sm text-[#0A1128] flex items-center gap-1.5"><Paperclip size={14}/> Attach files (optional)</div>
        <label className="zx-btn-outline cursor-pointer text-xs" data-testid="enquiry-file-upload">
          <Upload size={12}/> {busy ? "Uploading…" : "Add file"}
          <input type="file" className="hidden" onChange={upload} disabled={busy} />
        </label>
      </div>
      <div className="text-xs text-[#6B7280] mt-1">PDF, images, docs, spreadsheets, zip. Max 10 MB per file.</div>
      <div className="mt-2 space-y-1.5">
        {files.map(f => (
          <div key={f.id} className="flex items-center justify-between border border-[#E5E7EB] px-3 py-1.5 text-sm">
            <div className="min-w-0">
              <div className="truncate">{f.original_name}</div>
              <div className="text-xs text-[#6B7280]">{bytesHuman(f.size)}</div>
            </div>
            <div className="flex gap-2">
              <button onClick={()=>download(f)} className="zx-link text-xs flex items-center gap-1"><Download size={12}/>Download</button>
              <button onClick={()=>remove(f)} className="text-[#A11B1B] text-xs flex items-center gap-1"><Trash2 size={12}/></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function EnquiryPage() {
  const loc = useLocation();
  const nav = useNavigate();
  const { user } = useAuth();
  const [services, setServices] = useState([]);
  const [form, setForm] = useState({
    service_id: loc.state?.service?.id || "",
    service_name: loc.state?.service?.name || "",
    name: user?.name || "", email: user?.email || "", phone: user?.phone || "",
    requirement: "", message: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => { api.get("/services").then(r => setServices(r.data)); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const svc = services.find(s => s.id === form.service_id);
      const payload = { ...form, service_name: svc?.name || form.service_name };
      // Use authed endpoint if logged in so files can be attached
      const url = user && user.role ? "/enquiries" : "/enquiries/public";
      const { data } = await api.post(url, payload);
      setResult(data);
      toast.success(`Enquiry ${data.enquiry_number} received`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed");
    } finally { setSubmitting(false); }
  };

  return (
    <div>
      <Header />
      <div className="container-page py-10 grid grid-cols-1 md:grid-cols-3 gap-8">
        <div className="md:col-span-2">
          <h1 className="font-serif text-3xl font-bold text-[#0A1128]">Submit an Enquiry</h1>
          <p className="text-[#4B5563] mt-1">Tell us your requirement. We will respond by email with a plan, timeline and quote.</p>

          {result ? (
            <div className="zx-card mt-6" data-testid="enquiry-success">
              <div className="text-[#146C2E] font-semibold">Enquiry received.</div>
              <div className="text-sm text-[#0A1128] mt-2">Reference: <b>{result.enquiry_number}</b></div>
              <p className="text-sm text-[#4B5563] mt-2">Please save this reference. Our team will respond within 1 business day.</p>
              <EnquiryAttachments enquiryId={result.id} canManage={!!(user && user.role)} />
              {!user && (
                <p className="text-xs text-[#6B7280] mt-3">Tip: <a href="/register" className="zx-link">Create an account</a> to attach files, track your enquiries and place orders.</p>
              )}
              <div className="mt-4 flex gap-2">
                <button onClick={() => nav("/")} className="zx-btn-outline" data-testid="enquiry-home-btn">Return Home</button>
                {user && user.role && <button onClick={()=>nav("/dashboard")} className="zx-btn-primary">Go to Dashboard</button>}
              </div>
            </div>
          ) : (
          <form onSubmit={submit} className="zx-card mt-6 space-y-4" data-testid="enquiry-form">
            <div>
              <label className="zx-label">Service *</label>
              <select value={form.service_id} onChange={e=>setForm({...form, service_id: e.target.value})} className="zx-input" required data-testid="enquiry-service">
                <option value="">Select a service</option>
                {services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><label className="zx-label">Full Name *</label><input required data-testid="enquiry-name" className="zx-input" value={form.name} onChange={e=>setForm({...form, name: e.target.value})} /></div>
              <div><label className="zx-label">Email *</label><input required type="email" data-testid="enquiry-email" className="zx-input" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} /></div>
            </div>
            <div><label className="zx-label">Phone</label><input data-testid="enquiry-phone" className="zx-input" value={form.phone} onChange={e=>setForm({...form, phone: e.target.value})} /></div>
            <div><label className="zx-label">Requirement (one-line) *</label><input required data-testid="enquiry-requirement" className="zx-input" value={form.requirement} onChange={e=>setForm({...form, requirement: e.target.value})} /></div>
            <div><label className="zx-label">Detailed message</label><textarea rows={5} data-testid="enquiry-message" className="zx-input" value={form.message} onChange={e=>setForm({...form, message: e.target.value})} /></div>
            <div className="text-xs text-[#6B7280]">{user ? "Files can be attached after submitting." : "Log in first if you want to attach files (mockups, screenshots, PDFs)."}</div>
            <div className="pt-2">
              <button disabled={submitting} className="zx-btn-primary" data-testid="enquiry-submit-btn">{submitting ? "Submitting…" : "Submit Enquiry"}</button>
            </div>
          </form>
          )}
        </div>
        <aside className="space-y-4">
          <div className="zx-card">
            <div className="font-serif text-lg font-bold text-[#0A1128]">What to include</div>
            <ul className="text-sm text-[#4B5563] mt-2 space-y-1.5 list-disc pl-5">
              <li>What outcome you need</li>
              <li>Preferred timeline</li>
              <li>Budget (if fixed)</li>
              <li>Existing systems (if any)</li>
            </ul>
          </div>
          <div className="zx-card">
            <div className="font-serif text-lg font-bold text-[#0A1128]">Track later</div>
            <p className="text-sm text-[#4B5563] mt-2">You will receive a confirmation email with your enquiry reference number.</p>
          </div>
        </aside>
      </div>
      <Footer />
    </div>
  );
}
