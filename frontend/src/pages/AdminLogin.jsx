import { useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";

export default function AdminLogin() {
  const [step, setStep] = useState("password");
  const [form, setForm] = useState({ email: "", password: "" });
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submitPassword = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      localStorage.removeItem("zx_token");
      const { data } = await api.post("/admin-auth/login", form);
      setChallenge(data.challenge);
      setCode("");
      setStep("otp");
      toast.success("A sign-in code was sent to your admin email");
    } catch (e) {
      setError(e.response?.data?.detail || "Admin login failed");
    } finally { setBusy(false); }
  };

  const verify = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    if (!/^\d{6}$/.test(code)) {
      setError("Enter the six-digit email code.");
      setBusy(false);
      return;
    }
    try {
      const { data } = await api.post("/admin-auth/verify", { challenge, code });
      if (data.role !== "admin" || !data.access_token) throw new Error("Admin session was not created");
      localStorage.setItem("zx_token", data.access_token);
      const me = await api.get("/auth/me");
      if (me.data?.role !== "admin") throw new Error("Admin session verification failed");
      toast.success("Admin signed in");
      window.location.replace("/admin");
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Email verification failed");
    } finally { setBusy(false); }
  };

  return <div className="min-h-screen bg-[#F8F9FA] flex items-center justify-center p-4">
    <div className="zx-card w-full max-w-md">
      <div className="font-serif text-xl font-bold text-[#0A1128]">ZEROAXIS Admin</div>
      <p className="text-sm text-[#6B7280] mt-1">
        {step === "password" ? "Secure administrator sign in." : "Enter the six-digit code sent to your registered admin email."}
      </p>
      {step === "password" ? <form onSubmit={submitPassword} className="mt-6 space-y-4">
        <div><label className="zx-label">Admin email</label><input required type="email" autoComplete="username" className="zx-input" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></div>
        <div><label className="zx-label">Password</label><input required type="password" autoComplete="current-password" className="zx-input" value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></div>
        {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
        <button disabled={busy} className="zx-btn-primary w-full justify-center">{busy ? "Sending code…" : "Continue"}</button>
      </form> : <form onSubmit={verify} className="mt-6 space-y-4">
        <div><label className="zx-label">Email verification code</label><input autoFocus required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" className="zx-input tracking-[0.35em]" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,"").slice(0,6))}/></div>
        {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
        <button disabled={busy || code.length !== 6} className="zx-btn-primary w-full justify-center">{busy ? "Verifying…" : "Verify and sign in"}</button>
        <button type="button" disabled={busy} className="w-full text-sm text-[#00509E] underline" onClick={()=>{setStep("password");setCode("");setChallenge("");setError("");}}>Back to login</button>
      </form>}
    </div>
  </div>;
}
