import { useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";

export default function AdminLogin() {
  const [step, setStep] = useState("password");
  const [form, setForm] = useState({ email: "", password: "" });
  const [challenge, setChallenge] = useState("");
  const [secret, setSecret] = useState("");
  const [qrCode, setQrCode] = useState("");
  const [code, setCode] = useState("");
  const [recoveryToken, setRecoveryToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submitPassword = async (e) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      // Do not let a previous customer bearer token interfere with admin authentication.
      localStorage.removeItem("zx_token");
      const { data } = await api.post("/admin-auth/login", form);
      setChallenge(data.challenge);
      if (data.two_factor_setup_required) {
        setSecret(data.secret);
        setQrCode(data.qr_code_svg_base64 || "");
        setStep("setup");
      } else {
        setStep("otp");
      }
    } catch (e) {
      setError(e.response?.data?.detail || "Admin login failed");
    } finally { setBusy(false); }
  };

  const verify = async (e) => {
    e.preventDefault(); setBusy(true); setError("");
    if (!/^\d{6}$/.test(code)) { setError("Enter the 6-digit authenticator code."); setBusy(false); return; }
    try {
      const endpoint = step === "setup" ? "/admin-auth/setup" : "/admin-auth/verify";
      const { data } = await api.post(endpoint, { challenge, code });
      if (data.role === "admin" && data.access_token) {
        // Keep the existing bearer fallback in sync with the admin session.
        // This also handles browsers that do not persist the cross-origin cookie.
        localStorage.setItem("zx_token", data.access_token);
        const me = await api.get("/auth/me");
        if (me.data?.role !== "admin") {
          throw new Error("Admin session verification failed");
        }
        toast.success("Admin signed in");
        window.location.replace("/admin");
      } else {
        throw new Error("Admin session was not created");
      }
    } catch (e) {
      setError(e.response?.data?.detail || "Invalid authenticator code");
    } finally { setBusy(false); }
  };

  return <div className="min-h-screen bg-[#F8F9FA] flex items-center justify-center p-4">
    <div className="zx-card w-full max-w-md">
      <div className="font-serif text-xl font-bold text-[#0A1128]">ZEROAXIS Admin</div>
      <p className="text-sm text-[#6B7280] mt-1">
        {step === "password" ? "Secure administrator sign in." : step === "setup" ? "Set up your authenticator app." : "Enter your authenticator code."}
      </p>

      {step === "password" && <form onSubmit={submitPassword} className="mt-6 space-y-4">
        <div><label className="zx-label">Admin email</label><input required type="email" autoComplete="username" className="zx-input" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></div>
        <div><label className="zx-label">Password</label><input required type="password" autoComplete="current-password" className="zx-input" value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></div>
        {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
        <button disabled={busy} className="zx-btn-primary w-full justify-center">{busy ? "Checking…" : "Continue"}</button>
      </form>}

      {step === "setup" && <form onSubmit={verify} className="mt-6 space-y-4">
        <p className="text-sm text-[#4B5563]">Scan this QR code with Google Authenticator, Microsoft Authenticator, or another TOTP app.</p>
        {qrCode && <div className="mx-auto flex w-fit flex-col items-center rounded-lg border border-[#D8DEE8] bg-white p-4"><img src={`data:image/svg+xml;base64,${qrCode}`} alt="ZEROAXIS authenticator setup QR code" className="h-52 w-52" /><span className="mt-2 text-xs text-[#6B7280]">Scan using your authenticator app</span></div>}
        <div><label className="zx-label">Manual setup key (if QR scanning fails)</label><div className="zx-input font-mono break-all select-all">{secret}</div></div>
        <p className="text-xs text-[#6B7280]">After scanning, enter the six-digit code shown by your authenticator app to finish setup. Keep the setup key private.</p>
        <div><label className="zx-label">Authenticator code</label><input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" className="zx-input tracking-[0.35em]" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,"").slice(0,6))}/></div>
        {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
        <button disabled={busy} className="zx-btn-primary w-full justify-center">{busy ? "Activating…" : "Enable 2FA"}</button>
      </form>}

      {step === "otp" && <form onSubmit={verify} className="mt-6 space-y-4">
        <div><label className="zx-label">Authenticator code</label><input autoFocus required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" className="zx-input tracking-[0.35em]" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,"").slice(0,6))}/></div>
        {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
        <button disabled={busy} className="zx-btn-primary w-full justify-center">{busy ? "Verifying…" : "Verify and sign in"}</button>
        <button type="button" disabled={busy} className="w-full text-sm text-[#00509E] underline" onClick={async()=>{setBusy(true);setError("");try{const {data}=await api.post("/admin-auth/recovery/request",form);setRecoveryToken(data.recovery_token);setCode("");setStep("recovery");}catch(e){setError(e.response?.data?.detail||"Could not start recovery");}finally{setBusy(false);}}}>Can't access your authenticator? Recover by email</button>
      </form>}

      {step === "recovery" && <form onSubmit={async(e)=>{e.preventDefault();setBusy(true);setError("");try{const {data}=await api.post("/admin-auth/recovery/verify",{recovery_token:recoveryToken,code});setChallenge(data.challenge);setSecret(data.secret);setQrCode(data.qr_code_svg_base64||"");setCode("");setStep("setup");setError("");}catch(e){setError(e.response?.data?.detail||"Recovery verification failed");}finally{setBusy(false);}}} className="mt-6 space-y-4">
        <p className="text-sm text-[#4B5563]">Enter the six-digit recovery code sent to your registered admin email. The old authenticator will only be replaced after this code is verified.</p>
        <div><label className="zx-label">Email recovery code</label><input autoFocus required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" className="zx-input tracking-[0.35em]" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,"").slice(0,6))}/></div>
        {error && <div className="text-[#A11B1B] text-sm">{error}</div>}
        <button disabled={busy} className="zx-btn-primary w-full justify-center">{busy ? "Verifying…" : "Verify email code"}</button>
        <button type="button" disabled={busy} className="w-full text-sm text-[#00509E] underline" onClick={()=>{setStep("otp");setCode("");setError("");}}>Back to authenticator login</button>
      </form>}
    </div>
  </div>;
}
