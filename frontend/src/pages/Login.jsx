import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { toast } from "sonner";

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    const r = await login(form.email, form.password);
    setBusy(false);
    if (r.ok) {
      toast.success("Signed in");
      nav(r.user.role === "admin" ? "/admin" : "/dashboard");
    } else {
      setErr(r.error || "Login failed");
    }
  };

  return (
    <div>
      <Header />
      <div className="container-page py-16 max-w-md">
        <h1 className="font-serif text-2xl font-bold text-[#0A1128]">Customer Login</h1>
        <p className="text-sm text-[#6B7280] mt-1">Sign in to manage your orders and enquiries.</p>
        <form onSubmit={submit} className="zx-card mt-6 space-y-4" data-testid="login-form">
          <div><label className="zx-label">Email</label><input required type="email" data-testid="login-email" className="zx-input" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} /></div>
          <div><label className="zx-label">Password</label><input required type="password" data-testid="login-password" className="zx-input" value={form.password} onChange={e=>setForm({...form, password: e.target.value})} /></div>
          {err && <div className="text-[#A11B1B] text-sm" data-testid="login-error">{err}</div>}
          <button disabled={busy} className="zx-btn-primary w-full justify-center" data-testid="login-submit-btn">{busy ? "Signing in…" : "Sign in"}</button>
          <div className="text-sm text-[#4B5563]">No account? <Link to="/register" className="zx-link">Register</Link></div>
        </form>
      </div>
      <Footer />
    </div>
  );
}
