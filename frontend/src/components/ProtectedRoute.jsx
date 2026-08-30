import { Navigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";

export default function ProtectedRoute({ children, role }) {
  const { user, loading } = useAuth();
  if (loading || user === null) {
    return <div data-testid="loading-guard" className="container-page py-24 text-center text-[#6B7280]">Loading…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  if (role && user.role !== role) return <Navigate to={user.role === "admin" ? "/admin" : "/dashboard"} replace />;
  return children;
}
