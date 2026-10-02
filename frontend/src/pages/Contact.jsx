.import { useEffect, useState } from "react";
import api from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default function ContactPage() {
  const [c, setC] = useState({});
  useEffect(() => { api.get("/content").then(r => setC(r.data || {})); }, []);
  const contact = c.contact || {};
  return (
    <div>
      <Header />
      <div className="container-page py-10 max-w-3xl">
        <h1 className="font-serif text-3xl font-bold text-[#0A1128]">Contact</h1>
        <p className="text-[#4B5563] mt-1">Reach us for enquiries, quotes and support.</p>
        <div className="zx-card mt-6">
          <div className="text-sm text-[#0A1128] space-y-2">
            <div><span className="text-[#6B7280] w-24 inline-block">Email:</span> {contact.email || "contact@zeroaxis.in"}</div>
            <div><span className="text-[#6B7280] w-24 inline-block">Phone:</span> {contact.phone || "4703131236"}</div>
            <div><span className="text-[#6B7280] w-24 inline-block">Address:</span> {contact.address || "InstaSpaces VirtualOffice Kochi"}</div>
            <div><span className="text-[#6B7280] w-24 inline-block">Hours:</span> {contact.hours || "Monday – Sunday 10:00-10:00"}</div>
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}
