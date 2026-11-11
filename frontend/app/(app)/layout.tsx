"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken, getToken } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/incidents", label: "Incidents" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  if (!ready) return null;

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-52 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950 p-4">
        <div className="mb-6 text-lg font-bold tracking-wide">THRONEX</div>
        <nav className="flex flex-1 flex-col gap-1 text-sm">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={`rounded px-3 py-2 ${active ? "bg-zinc-800 text-white" : "text-zinc-400 hover:bg-zinc-900"}`}>
                {item.label}
              </Link>
            );
          })}
          <a href="http://localhost:3001" target="_blank" rel="noreferrer" className="rounded px-3 py-2 text-zinc-400 hover:bg-zinc-900">
            Grafana ↗
          </a>
        </nav>
        <button
          onClick={() => {
            clearToken();
            router.replace("/login");
          }}
          className="rounded px-3 py-2 text-left text-sm text-zinc-400 hover:bg-zinc-900"
        >
          Sign out
        </button>
      </aside>
      <main className="min-w-0 flex-1 p-6">{children}</main>
    </div>
  );
}