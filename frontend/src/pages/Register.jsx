import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";

export default function RegisterPage() {
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "", phone: "" });
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState("details");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const requestOtp = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await api.post("/auth/register", form);
      setStep("otp");
      toast.success("Verification code sent");
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || "Unable to send verification code");
    } finally { setBusy(false); }
  };

  const verifyOtp = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const { data } = await api.post("/auth/register/verify-otp", { email: form.email, otp });
      toast.success("Account created");
      nav(data.role === "admin" ? "/admin" : "/dashboard");
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || "Invalid verification code");
    } finally { setBusy(false); }
  };

  return (
    <div>
      <Header />
      <div className="container-page py-16 max-w-md">
        <h1 className="font-serif text-2xl font-bold text-[#0A1128]">Create Account</h1>
        <p className="text-sm text-[#6B7280] mt-1">{step === "details" ? "Register as a customer to place orders." : "Enter the 6-digit code sent to " + form.email + "."}</p>
        {step === "details" ? (
          <form onSubmit={requestOtp} className="zx-card mt-6 space-y-4" data-testid="register-form">
            <div><label className="zx-label">Full Name</label><input required minLength={2} data-testid="register-name" className="zx-input" value={form.name} onChange={e=>setForm({...form, name:e.target.value})} /></div>
            <div><label className="zx-label">Email</label><input required type="email" data-testid="register-email" className="zx-input" value={form.email} onChange={e=>setForm({...form, email:e.target.value})} /></div>
            <div><label className="zx-label">Phone</label><input data-testid="register-phone" className="zx-input" value={form.phone} onChange={e=>setForm({...form, phone:e.target.value})} /></div>
            <div><label className="zx-label">Password</label><input required minLength={6} type="password" data-testid="register-password" className="zx-input" value={form.password} onChange={e=>setForm({...form, password:e.target.value})} /></div>
            {err && <div className="text-[#A11B1B] text-sm" data-testid="register-error">{err}</div>}
            <button disabled={busy} className="zx-btn-primary w-full justify-center">{busy ? "Sending code…" : "Continue with email verification"}</button>
            <div className="text-sm text-[#4B5563]">Have an account? <Link to="/login" className="zx-link">Sign in</Link></div>
          </form>
        ) : (
          <form onSubmit={verifyOtp} className="zx-card mt-6 space-y-4">
            <div><label className="zx-label">Email verification code</label><input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" className="zx-input tracking-[0.35em]" value={otp} onChange={e=>setOtp(e.target.value.replace(/\D/g,"").slice(0,6))} /></div>
            {err && <div className="text-[#A11B1B] text-sm">{err}</div>}
            <button disabled={busy || otp.length !== 6} className="zx-btn-primary w-full justify-center">{busy ? "Verifying…" : "Verify email & create account"}</button>
            <button type="button" disabled={busy} onClick={() => { setStep("details"); setOtp(""); setErr(""); }} className="text-sm zx-link">Back</button>
          </form>
        )}
      </div>
      <Footer />
    </div>
  );
}