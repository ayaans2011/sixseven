import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { toast } from "sonner";
import api from "@/lib/api";

export default function LoginPage() {
  const { login } = useAuth();
  const [params] = useSearchParams();
  const resetToken = params.get("reset_token") || "";
  const nav = useNavigate();
  const [form, setForm] = useState({ email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [resetConfirm, setResetConfirm] = useState("");

  const resetSubmit = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    if (resetPassword.length < 6) { setErr("Password must be at least 6 characters."); setBusy(false); return; }
    if (resetPassword !== resetConfirm) { setErr("Passwords do not match."); setBusy(false); return; }
    try {
      await api.post("/auth/reset-password", { token: resetToken, new_password: resetPassword });
      toast.success("Password updated");
      window.history.replaceState({}, "", "/login");
      window.location.reload();
    } catch (e) { setErr(e.response?.data?.detail || "Unable to reset password"); }
    finally { setBusy(false); }
  };

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
        <h1 className="font-serif text-2xl font-bold text-[#0A1128]">{resetToken ? "Reset password" : "Customer Login"}</h1>
        <p className="text-sm text-[#6B7280] mt-1">{resetToken ? "Choose a new password for your account." : "Sign in to manage your orders and enquiries."}</p>
        <form onSubmit={resetToken ? resetSubmit : submit} className="zx-card mt-6 space-y-4" data-testid="login-form">
          {!resetToken && <div><label className="zx-label">Email</label><input required type="email" data-testid="login-email" className="zx-input" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} /></div>}
          {resetToken ? <><div><label className="zx-label">New password</label><input required minLength={6} type="password" className="zx-input" value={resetPassword} onChange={e=>setResetPassword(e.target.value)} /></div><div><label className="zx-label">Confirm password</label><input required minLength={6} type="password" className="zx-input" value={resetConfirm} onChange={e=>setResetConfirm(e.target.value)} /></div></> : <div><label className="zx-label">Password</label><input required type="password" data-testid="login-password" className="zx-input" value={form.password} onChange={e=>setForm({...form, password: e.target.value})} /></div>}
          {err && <div className="text-[#A11B1B] text-sm" data-testid="login-error">{err}</div>}
          <button disabled={busy} className="zx-btn-primary w-full justify-center" data-testid="login-submit-btn">{busy ? (resetToken ? "Updating…" : "Signing in…") : (resetToken ? "Update password" : "Sign in")}</button>
          {!resetToken && <div className="text-sm"><Link to="/forgot-password" className="zx-link">Forgot password?</Link></div>}
          {!resetToken && <div className="text-sm text-[#4B5563]">No account? <Link to="/register" className="zx-link">Register</Link></div>}
          {resetToken && <div className="text-sm"><Link to="/login" className="zx-link">Back to login</Link></div>}
        </form>
      </div>
      <Footer />
    </div>
  );
}
