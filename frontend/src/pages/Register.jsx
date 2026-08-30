import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { toast } from "sonner";

export default function RegisterPage() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    const r = await register(form);
    setBusy(false);
    if (r.ok) { toast.success("Account created"); nav("/dashboard"); }
    else setErr(r.error || "Registration failed");
  };

  return (
    <div>
      <Header />
      <div className="container-page py-16 max-w-md">
        <h1 className="font-serif text-2xl font-bold text-[#0A1128]">Create Account</h1>
        <p className="text-sm text-[#6B7280] mt-1">Register as a customer to place orders.</p>
        <form onSubmit={submit} className="zx-card mt-6 space-y-4" data-testid="register-form">
          <div><label className="zx-label">Full Name</label><input required minLength={2} data-testid="register-name" className="zx-input" value={form.name} onChange={e=>setForm({...form, name: e.target.value})} /></div>
          <div><label className="zx-label">Email</label><input required type="email" data-testid="register-email" className="zx-input" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} /></div>
          <div><label className="zx-label">Phone</label><input data-testid="register-phone" className="zx-input" value={form.phone} onChange={e=>setForm({...form, phone: e.target.value})} /></div>
          <div><label className="zx-label">Password</label><input required minLength={6} type="password" data-testid="register-password" className="zx-input" value={form.password} onChange={e=>setForm({...form, password: e.target.value})} /></div>
          {err && <div className="text-[#A11B1B] text-sm" data-testid="register-error">{err}</div>}
          <button disabled={busy} className="zx-btn-primary w-full justify-center" data-testid="register-submit-btn">{busy ? "Creating…" : "Create Account"}</button>
          <div className="text-sm text-[#4B5563]">Have an account? <Link to="/login" className="zx-link">Sign in</Link></div>
        </form>
      </div>
      <Footer />
    </div>
  );
}
