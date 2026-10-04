import { useState } from "react";
import { Link } from "react-router-dom";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const { data } = await api.post("/auth/forgot-password", { email });
      setSent(true);
      toast.success("Check your email");
      return data;
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || "Unable to send reset link");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Header />
      <div className="container-page py-16 max-w-md">
        <h1 className="font-serif text-2xl font-bold text-[#0A1128]">Forgot password</h1>
        <p className="text-sm text-[#6B7280] mt-1">
          Enter your account email and we’ll send a password reset link.
        </p>
        <form onSubmit={submit} className="zx-card mt-6 space-y-4">
          <div>
            <label className="zx-label">Email</label>
            <input
              required
              type="email"
              autoComplete="email"
              className="zx-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          {err && <div className="text-[#A11B1B] text-sm">{err}</div>}
          {sent && (
            <div className="text-sm text-green-700">
              If an account exists for this email, a reset link has been sent. Check your inbox and spam folder.
            </div>
          )}
          <button disabled={busy} className="zx-btn-primary w-full justify-center">
            {busy ? "Sending…" : "Send reset link"}
          </button>
          <div className="text-sm text-[#4B5563]">
            Remember your password? <Link to="/login" className="zx-link">Sign in</Link>
          </div>
        </form>
      </div>
      <Footer />
    </div>
  );
}
