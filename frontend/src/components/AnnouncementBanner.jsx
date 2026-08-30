import { useEffect, useState } from "react";
import api from "@/lib/api";

export default function AnnouncementBanner() {
  const [ann, setAnn] = useState(null);
  useEffect(() => {
    api.get("/content/announcement").then(r => {
      const v = r.data?.value || {};
      if (v.active && v.text) setAnn(v);
    }).catch(()=>{});
  }, []);
  if (!ann) return null;
  return (
    <div data-testid="announcement-banner" className="bg-[#00509E] text-white">
      <div className="container-page py-2 text-sm flex items-center justify-center gap-2 text-center">
        <span aria-hidden="true">●</span>
        <span>{ann.text}</span>
      </div>
    </div>
  );
}
