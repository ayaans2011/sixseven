import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import api from "@/lib/api";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const token = params.get("token") || "";
  const [otp, setOtp] = useState("");
  const [value, setValue] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(e) {
    e.preventDefault(); setError("");
    if (!token) return setError("This reset link is invalid.");
    if (!/^\d{6}$/.test(otp)) return setError("Enter the 6-digit verification code from your email.");
    if (value.length < 6) return setError("Use at least 6 characters.");
    if (value !== again) return setError("The two entries do not match.");
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, otp, new_password: value });
      setDone(true);
      setTimeout(() => nav("/login"), 1200);
    } catch (e) {
      setError(e.response?.data?.detail || "This reset link is invalid or expired.");
    } finally { setBusy(false); }
  }

  return <div><Header /><div className="container-page py-16 max-w-md">
    <h1 className="font-serif text-2xl font-bold text-[#0A1128]">Reset password</h1>
    <p className="text-sm text-[#6B7280] mt-1">Enter the 6-digit code from your email and choose a new password.</p>
    <form onSubmit={submit} className="zx-card mt-6 space-y-4">
      <div><label className="zx-label">Email verification code</label><input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" className="zx-input tracking-[0.35em]" value={otp} onChange={e=>setOtp(e.target.value.replace(/\D/g,"").slice(0,6))} /></div><div><label className="zx-label">New password</label><input required minLength={6} type="password" autoComplete="new-password" className="zx-input" value={value} onChange={e=>setValue(e.target.value)} /></div>
      <div><label className="zx-label">Confirm password</label><input required minLength={6} type="password" autoComplete="new-password" className="zx-input" value={again} onChange={e=>setAgain(e.target.value)} /></div>
      {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
      {done && <div className="text-sm text-green-700">Updated. Redirecting to login…</div>}
      <button disabled={busy || done} className="zx-btn-primary w-full justify-center">{busy ? "Updating…" : "Update password"}</button>
      <div className="text-sm"><Link to="/login" className="zx-link">Back to login</Link></div>
    </form>
  </div><Footer /></div>;
}
