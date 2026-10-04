import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider } from "@/lib/auth";
import ProtectedRoute from "@/components/ProtectedRoute";
import Home from "@/pages/Home";
import About from "@/pages/About";
import ServicesPage from "@/pages/Services";
import Enquiry from "@/pages/Enquiry";
import TrackOrder from "@/pages/TrackOrder";
import Contact from "@/pages/Contact";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import CustomerDashboard from "@/pages/CustomerDashboard";
import AdminDashboard from "@/pages/AdminDashboard";
import "@/App.css";

function OrdersRedirect() {
  return <Navigate to="/dashboard/orders" replace />;
}

function EntryRoute() {
  const [params] = useSearchParams();
  return params.get("reset_token") ? <Login /> : <Home />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster richColors position="top-right" />
        <Routes>
          <Route path="/" element={<EntryRoute />} />
          <Route path="/about" element={<About />} />
          <Route path="/services" element={<ServicesPage />} />
          <Route path="/enquiry" element={<Enquiry />} />
          <Route path="/track" element={<TrackOrder />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/orders" element={<ProtectedRoute><OrdersRedirect /></ProtectedRoute>} />
          <Route path="/dashboard/*" element={<ProtectedRoute><CustomerDashboard /></ProtectedRoute>} />
          <Route path="/admin/*" element={<ProtectedRoute role="admin"><AdminDashboard /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
