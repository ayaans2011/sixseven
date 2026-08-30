import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Menu, X, User } from "lucide-react";
import { useState } from "react";
import AnnouncementBanner from "@/components/AnnouncementBanner";
import MessageBell from "@/components/MessageBell";

export default function Header() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);

  const links = [
    { to: "/", label: "Home", end: true },
    { to: "/about", label: "About" },
    { to: "/services", label: "Services" },
    { to: "/enquiry", label: "Enquiry" },
    { to: "/orders", label: "Orders" },
    { to: "/track", label: "Track Order" },
    { to: "/contact", label: "Contact" },
  ];

  return (
    <>
      <AnnouncementBanner />
      <header data-testid="site-header" className="border-b border-[#E5E7EB] bg-white sticky top-0 z-30">
      <div className="container-page flex items-center h-16 justify-between">
        <Link to="/" data-testid="logo-link" className="flex items-baseline gap-2">
          <span className="font-serif text-2xl font-bold text-[#0A1128] tracking-tight">ZEROAXIS</span>
          <span className="hidden sm:inline text-[11px] text-[#6B7280] uppercase tracking-wider">Technology &amp; Digital Services</span>
        </Link>

        <nav className="hidden lg:flex items-center gap-1">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              data-testid={`nav-${l.label.toLowerCase().replace(/\s+/g,'-')}`}
              className={({ isActive }) =>
                `px-3 py-2 text-sm font-medium ${isActive ? "text-[#00509E] border-b-2 border-[#00509E]" : "text-[#0A1128] hover:text-[#00509E]"}`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>

        <div className="hidden lg:flex items-center gap-2">
          {user && user.role ? (
            <>
              <MessageBell />
              <Link
                to={user.role === "admin" ? "/admin" : "/dashboard"}
                data-testid="header-dashboard-link"
                className="text-sm font-medium text-[#0A1128] px-3 py-2 hover:text-[#00509E] flex items-center gap-1"
              >
                <User size={16} /> {user.name?.split(" ")[0] || "Account"}
              </Link>
              <button
                onClick={() => { logout(); nav("/"); }}
                data-testid="header-logout-btn"
                className="zx-btn-outline"
              >Logout</button>
            </>
          ) : (
            <>
              <Link to="/login" data-testid="header-login-link" className="zx-btn-outline">Login</Link>
              <Link to="/enquiry" data-testid="header-order-now-btn" className="zx-btn-primary">Order Now</Link>
            </>
          )}
        </div>

        <button
          onClick={() => setOpen(!open)}
          data-testid="mobile-menu-toggle"
          className="lg:hidden p-2 border border-[#E5E7EB] rounded-sm"
          aria-label="Toggle menu"
        >
          {open ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>

      {open && (
        <div className="lg:hidden border-t border-[#E5E7EB] bg-white">
          <div className="container-page py-3 flex flex-col">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                onClick={() => setOpen(false)}
                data-testid={`mobile-nav-${l.label.toLowerCase().replace(/\s+/g,'-')}`}
                className={({ isActive }) =>
                  `py-2 text-sm ${isActive ? "text-[#00509E] font-semibold" : "text-[#0A1128]"}`
                }
              >{l.label}</NavLink>
            ))}
            {user && user.role ? (
              <>
                <Link onClick={() => setOpen(false)} to={user.role === "admin" ? "/admin" : "/dashboard"} className="py-2 text-sm text-[#0A1128]" data-testid="mobile-dashboard-link">Dashboard</Link>
                <button onClick={() => { setOpen(false); logout(); nav("/"); }} className="py-2 text-sm text-left text-[#0A1128]" data-testid="mobile-logout-btn">Logout</button>
              </>
            ) : (
              <>
                <Link onClick={() => setOpen(false)} to="/login" className="py-2 text-sm text-[#0A1128]" data-testid="mobile-login-link">Login</Link>
                <Link onClick={() => setOpen(false)} to="/enquiry" className="py-2 text-sm text-[#00509E] font-semibold" data-testid="mobile-order-now-link">Order Now</Link>
              </>
            )}
          </div>
        </div>
      )}
      </header>
    </>
  );
}
