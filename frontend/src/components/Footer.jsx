import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer data-testid="site-footer" className="bg-[#0A1128] text-[#CBD2DA] mt-16">
      <div className="container-page py-10 grid grid-cols-1 md:grid-cols-4 gap-8">
        <div>
          <div className="font-serif text-xl font-bold text-white">ZEROAXIS</div>
          <p className="text-xs mt-2 text-[#94A3B8]">Technology &amp; Digital Services. Established 2020.</p>
          <p className="text-xs mt-2 text-[#94A3B8]">Main Programmers: Team Zeroaxis</p>
        </div>
        <div>
          <div className="text-white text-sm font-semibold mb-2">Company</div>
          <ul className="space-y-1 text-sm">
            <li><Link to="/about" className="hover:text-white">About</Link></li>
            <li><Link to="/services" className="hover:text-white">Services</Link></li>
            <li><Link to="/contact" className="hover:text-white">Contact</Link></li>
          </ul>
        </div>
        <div>
          <div className="text-white text-sm font-semibold mb-2">Customers</div>
          <ul className="space-y-1 text-sm">
            <li><Link to="/enquiry" className="hover:text-white">Submit Enquiry</Link></li>
            <li><Link to="/track" className="hover:text-white">Track Order</Link></li>
            <li><Link to="/login" className="hover:text-white">Customer Login</Link></li>
          </ul>
        </div>
        <div>
          <div className="text-white text-sm font-semibold mb-2">Legal</div>
          <ul className="space-y-1 text-sm">
            <li>Udyam / MSME: <span className="text-[#94A3B8]">UDYAM-KL-12-0143574</span></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-[#1E2A44]">
        <div className="container-page py-4 text-xs text-[#94A3B8] flex flex-col md:flex-row justify-between gap-2">
          <span>© {new Date().getFullYear()} Zeroaxis.2025 All rights reserved.</span>
          <span>Built and maintained by Zeroaxis.</span>
        </div>
      </div>
    </footer>
  );
}
