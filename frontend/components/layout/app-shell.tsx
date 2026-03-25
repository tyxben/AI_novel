"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import {
  BookOpenText,
  Clapperboard,
  FileStack,
  ListTodo,
  Settings2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "创作台", icon: Sparkles },
  { href: "/novel", label: "小说", icon: BookOpenText },
  { href: "/video", label: "视频", icon: Clapperboard },
  { href: "/ppt", label: "PPT", icon: FileStack },
  { href: "/tasks", label: "任务", icon: ListTodo },
  { href: "/settings", label: "设置", icon: Settings2 },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";

  return (
    <div className="min-h-screen px-4 py-5 md:px-6">
      <div className="mx-auto grid max-w-7xl gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="rounded-[28px] border border-white/70 bg-white/75 p-5 shadow-panel backdrop-blur">
          <div className="mb-8">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent">
              AI 创作工坊
            </p>
            <h1 className="mt-3 text-2xl font-semibold text-ink">
              小说、视频、PPT 一站创作
            </h1>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              多 Agent 驱动的中文创作平台，统一管理所有创作项目和后台任务。
            </p>
          </div>

          <nav className="space-y-1.5">
            {navItems.map(({ href, label, icon: Icon }) => {
              const active = isActive(pathname, href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium transition",
                    active
                      ? "bg-accent/10 text-accent"
                      : "text-slate-700 hover:bg-shell hover:text-ink"
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4",
                      active ? "text-accent" : "text-slate-400"
                    )}
                  />
                  <span>{label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="mt-10 rounded-2xl bg-ink px-4 py-4 text-sm text-slate-200">
            <p className="font-medium text-white">Next.js 前端</p>
            <p className="mt-2 leading-6 text-slate-300">
              独立前端应用，通过 REST API 对接后端任务队列和项目接口。
            </p>
          </div>
        </aside>

        <main className="rounded-[28px] border border-white/70 bg-white/80 shadow-panel backdrop-blur">
          {children}
        </main>
      </div>
    </div>
  );
}
