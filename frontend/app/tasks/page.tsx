"use client";

import { useState } from "react";
import { TaskList } from "@/components/feature/task-list";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";

const FILTER_OPTIONS = [
  { value: "", label: "全部" },
  { value: "小说", label: "小说" },
  { value: "视频", label: "视频" },
  { value: "PPT", label: "PPT" },
];

export default function TasksPage() {
  const [filterKind, setFilterKind] = useState("");

  return (
    <>
      <PageHeader
        eyebrow="任务"
        title="任务中心"
        description="查看所有后台任务的运行状态、进度和结果。运行中任务自动刷新。"
      />
      <div className="space-y-5 px-6 py-6 md:px-8">
        <Panel title="任务列表">
          {/* Filter tabs */}
          <div className="mb-4 flex gap-2">
            {FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setFilterKind(opt.value)}
                className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition ${
                  filterKind === opt.value
                    ? "bg-accent text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-shell"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <TaskList filterKind={filterKind || undefined} />
        </Panel>
      </div>
    </>
  );
}
