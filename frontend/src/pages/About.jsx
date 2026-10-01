import { useEffect, useState } from "react";
import api from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default function AboutPage() {
  const [c, setC] = useState({});
  useEffect(() => { api.get("/content").then(r => setC(r.data || {})); }, []);
  const about = c.about || {};
  const programmer = c.programmer || {};
  return (
    <div>
      <Header />
      <div className="container-page py-12 max-w-3xl">
        <h1 className="font-serif text-3xl font-bold text-[#0A1128]">{about.title || "About Zeroaxis"}</h1>
        <p className="text-[#4B5563] mt-4 leading-relaxed">{about.body}</p>
        <div className="zx-card mt-8">
          <div className="text-xs font-semibold uppercase text-[#00509E]">Company Snapshot</div>
          <ul className="mt-3 text-sm text-[#0A1128] space-y-1.5">
            <li><span className="text-[#6B7280] w-32 inline-block">Established:</span> {about.established || "2020"}</li>
            <li><span className="text-[#6B7280] w-32 inline-block">Experience:</span> {about.experience_years || "5"} years</li>
            <li><span className="text-[#6B7280] w-32 inline-block">Main Programmer:</span> {programmer.name || "Zeroaxis Team"}</li>
          </ul>
        </div>
      </div>
      <Footer />
    </div>
  );
}
