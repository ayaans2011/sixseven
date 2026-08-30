import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default function ServicesPage() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/services").then(r => setItems(r.data)); }, []);
  return (
    <div>
      <Header />
      <div className="container-page py-10">
        <h1 className="font-serif text-3xl font-bold text-[#0A1128]">Services</h1>
        <p className="text-[#4B5563] mt-1">All services offered by Zeroaxis.</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-8">
          {items.map(s => (
            <div key={s.id} data-testid={`services-list-${s.slug}`} className="zx-card">
              <div className="text-xs font-semibold uppercase text-[#00509E] tracking-wider">{s.category}</div>
              <h3 className="font-serif text-lg font-bold mt-1">{s.name}</h3>
              <p className="text-sm text-[#4B5563] mt-2 leading-relaxed">{s.description}</p>
              <div className="flex justify-between items-center mt-4">
                <span className="font-semibold">₹{Number(s.price).toLocaleString('en-IN')}</span>
                <Link to="/enquiry" state={{ service: s }} className="zx-link text-sm">Enquire →</Link>
              </div>
            </div>
          ))}
        </div>
      </div>
      <Footer />
    </div>
  );
}
