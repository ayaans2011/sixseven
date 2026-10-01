import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { ArrowRight, ShieldCheck, Clock, FileText, Users, Server } from "lucide-react";

const HERO_IMG = "https://images.pexels.com/photos/12903168/pexels-photo-12903168.jpeg";
const AYAAN_IMG = "https://images.unsplash.com/photo-1522071820081-009f0129c71c";
const TECH_IMG  = "https://images.unsplash.com/photo-1785682231847-93265d8e633d";

export default function Home() {
  const [services, setServices] = useState([]);
  const [content, setContent] = useState({});

  useEffect(() => {
    api.get("/services").then(r => setServices(r.data)).catch(()=>{});
    api.get("/content").then(r => setContent(r.data || {})).catch(()=>{});
  }, []);

  const hero = content.hero || {};
  const about = content.about || {};
  const programmer = content.programmer || {};
  const udyam = content.udyam || {};
  const why = content.why || { points: [] };
  const contact = content.contact || {};

  return (
    <div>
      <Header />

      {/* Hero */}
      <section data-testid="hero-section" className="border-b border-[#E5E7EB] bg-white">
        <div className="container-page grid grid-cols-1 md:grid-cols-2 gap-10 py-12 md:py-16 items-center">
          <div className="zx-fade-in">
            <div className="text-xs font-semibold tracking-widest text-[#00509E] uppercase mb-3">
              {hero.tagline || "Established Technology & Digital Services"}
            </div>
            <h1 className="font-serif text-3xl md:text-4xl lg:text-5xl font-bold text-[#0A1128] leading-tight">
              {hero.headline || "Reliable technology work, delivered the traditional way."}
            </h1>
            <p className="mt-4 text-[#4B5563] text-base leading-relaxed">
              {hero.subtext || "Zeroaxis provides technology and digital services with a focus on quality, accountability and long-term reliability."}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/enquiry" data-testid="hero-enquiry-btn" className="zx-btn-primary">Submit an Enquiry <ArrowRight size={16} /></Link>
              <Link to="/services" data-testid="hero-services-btn" className="zx-btn-outline">View Services</Link>
            </div>
            <div className="mt-8 grid grid-cols-3 gap-4 text-sm">
              <div><div className="font-serif text-2xl font-bold text-[#0A1128]">{about.experience_years || "5"}+</div><div className="text-[#6B7280]">Years of experience</div></div>
              <div><div className="font-serif text-2xl font-bold text-[#0A1128]">{about.established || "2020"}</div><div className="text-[#6B7280]">Established</div></div>
              <div><div className="font-serif text-2xl font-bold text-[#0A1128]">100%</div><div className="text-[#6B7280]">Delivered by Zeroaxis Team</div></div>
            </div>
          </div>
          <div className="border border-[#E5E7EB] p-1 bg-white">
            <img src={HERO_IMG} alt="Zeroaxis office" className="w-full h-72 md:h-96 object-cover" loading="lazy" />
          </div>
        </div>
      </section>

      {/* Services */}
      <section data-testid="services-section" className="bg-[#F8F9FA] border-b border-[#E5E7EB]">
        <div className="container-page zx-section">
          <div className="flex items-end justify-between mb-8">
            <div>
              <h2 className="font-serif text-2xl md:text-3xl font-bold text-[#0A1128]">Our Services</h2>
              <p className="text-[#6B7280] mt-1 text-sm">Straightforward technology and digital services.</p>
            </div>
            <Link to="/services" className="zx-link text-sm hidden sm:inline">View all</Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {services.slice(0,6).map(s => (
              <div key={s.id} data-testid={`service-card-${s.slug}`} className="zx-card">
                <div className="text-xs font-semibold uppercase text-[#00509E] tracking-wider">{s.category}</div>
                <h3 className="font-serif text-lg font-bold text-[#0A1128] mt-1">{s.name}</h3>
                <p className="text-sm text-[#4B5563] mt-2 leading-relaxed line-clamp-3">{s.description}</p>
                <div className="mt-4 flex items-center justify-between">
                  <span className="text-[#0A1128] font-semibold">₹{Number(s.price).toLocaleString('en-IN')}</span>
                  <Link to="/enquiry" state={{ service: s }} className="zx-link text-sm">Enquire →</Link>
                </div>
              </div>
            ))}
            {services.length === 0 && <div className="text-sm text-[#6B7280]">Loading services…</div>}
          </div>
        </div>
      </section>

      {/* Why Zeroaxis */}
      <section data-testid="why-section" className="bg-white border-b border-[#E5E7EB]">
        <div className="container-page zx-section grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
          <div>
            <h2 className="font-serif text-2xl md:text-3xl font-bold text-[#0A1128]">Why Zeroaxis</h2>
            <p className="text-[#4B5563] mt-3 leading-relaxed">A traditional, careful approach to technology — no shortcuts, no unnecessary complexity.</p>
            <ul className="mt-6 space-y-3">
              {(why.points || []).map((p, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <ShieldCheck size={18} className="text-[#00509E] mt-0.5" />
                  <span className="text-sm text-[#0A1128]">{p}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="border border-[#E5E7EB] p-1"><img src={TECH_IMG} alt="Technology" className="w-full h-72 object-cover" loading="lazy" /></div>
        </div>
      </section>

      {/* About */}
      <section data-testid="about-section" className="bg-[#F8F9FA] border-b border-[#E5E7EB]">
        <div className="container-page zx-section">
          <div className="max-w-3xl">
            <h2 className="font-serif text-2xl md:text-3xl font-bold text-[#0A1128]">{about.title || "About Zeroaxis"}</h2>
            <p className="text-[#4B5563] mt-3 leading-relaxed">{about.body}</p>
          </div>
        </div>
      </section>

      {/* Programmer */}
      <section data-testid="programmer-section" className="bg-white border-b border-[#E5E7EB]">
        <div className="container-page zx-section grid grid-cols-1 md:grid-cols-3 gap-8 items-center">
          <div className="border border-[#E5E7EB] p-1 md:col-span-1"><img src={AYAAN_IMG} alt="Ayaan" className="w-full h-64 object-cover" loading="lazy" /></div>
          <div className="md:col-span-2">
            <div className="text-xs font-semibold uppercase tracking-widest text-[#00509E]">{programmer.title || "Main Programmer"}</div>
            <h2 className="font-serif text-2xl md:text-3xl font-bold text-[#0A1128] mt-1">{programmer.name || "Ayaan"}</h2>
            <p className="text-[#4B5563] mt-3 leading-relaxed">{programmer.bio}</p>
          </div>
        </div>
      </section>

      {/* How ordering works */}
      <section data-testid="how-it-works" className="bg-[#F8F9FA] border-b border-[#E5E7EB]">
        <div className="container-page zx-section">
          <h2 className="font-serif text-2xl md:text-3xl font-bold text-[#0A1128]">How ordering works</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6">
            {[
              { n: "01", t: "Submit an enquiry", d: "Tell us what you need. We reply with details and a quote.", icon: FileText },
              { n: "02", t: "Place an order", d: "Register or login and place an order for a service.", icon: Users },
              { n: "03", t: "Submit payment", d: "Pay via UPI/Bank and submit reference. Admin verifies.", icon: ShieldCheck },
              { n: "04", t: "Track & receive", d: "Track order status until completion.", icon: Clock },
            ].map((s) => (
              <div key={s.n} className="zx-card">
                <div className="flex items-center gap-2 text-[#00509E] text-xs font-semibold">
                  <s.icon size={16} /> STEP {s.n}
                </div>
                <div className="font-serif text-lg font-bold text-[#0A1128] mt-2">{s.t}</div>
                <p className="text-sm text-[#4B5563] mt-1 leading-relaxed">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Udyam */}
      <section data-testid="udyam-section" className="bg-white border-b border-[#E5E7EB]">
        <div className="container-page zx-section grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
          <div>
            <h2 className="font-serif text-2xl font-bold text-[#0A1128]">Udyam / MSME Registration</h2>
            <p className="text-[#4B5563] mt-2 leading-relaxed">
              {udyam.registered
                ? `Registered under Udyam. Number: ${udyam.number}`
                : "Zeroaxis will publish its official Udyam/MSME registration details on this page once the registration is verified."}
            </p>
            <p className="text-[#6B7280] text-xs mt-2">Placeholder: {udyam.number}</p>
          </div>
          <div className="zx-card">
            <div className="flex items-center gap-2 text-[#00509E] font-semibold"><Server size={16} /> Business Details</div>
            <ul className="mt-3 text-sm text-[#0A1128] space-y-1.5">
              <li><span className="text-[#6B7280] w-24 inline-block">Company:</span> ZEROAXIS</li>
              <li><span className="text-[#6B7280] w-24 inline-block">Established:</span> {about.established || "2020"}</li>
              <li><span className="text-[#6B7280] w-24 inline-block">Experience:</span> {about.experience_years || "5"} years</li>
              <li><span className="text-[#6B7280] w-24 inline-block">Programmer:</span> {programmer.name || "Zeroaxis Team"}</li>
            </ul>
          </div>
        </div>
      </section>

      {/* CTA + Contact */}
      <section data-testid="cta-section" className="bg-[#0A1128] text-white">
        <div className="container-page zx-section grid grid-cols-1 md:grid-cols-3 gap-8 items-start">
          <div className="md:col-span-2">
            <h2 className="font-serif text-2xl md:text-3xl font-bold">Ready to start a project?</h2>
            <p className="text-[#CBD2DA] mt-2">Submit an enquiry describing what you need. We will respond with a plan, timeline and price.</p>
            <div className="mt-5 flex gap-3">
              <Link to="/enquiry" data-testid="cta-enquiry-btn" className="zx-btn-primary">Submit Enquiry</Link>
              <Link to="/register" data-testid="cta-register-btn" className="zx-btn-outline" style={{ background: "transparent", color: "#fff", borderColor: "#fff" }}>Create Account</Link>
            </div>
          </div>
          <div className="text-sm text-[#CBD2DA]">
            <div className="font-serif text-white text-lg mb-2">Contact</div>
            <div><span className="text-[#94A3B8]">Email:</span> {contact.email || "ayaanss2011@gmail.com"}</div>
            <div><span className="text-[#94A3B8]">Phone:</span> {contact.phone || "+91 8590908959"}</div>
            <div><span className="text-[#94A3B8]">Hours:</span> {contact.hours}</div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
