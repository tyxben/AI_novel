import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";

export function WorkspaceFrame({
  kind,
  title,
  intro,
  stages,
  rightTitle,
  rightBody
}: {
  kind: string;
  title: string;
  intro: string;
  stages: Array<{ label: string; detail: string; status: string }>;
  rightTitle: string;
  rightBody: string;
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_360px]">
      <Panel
        title={title}
        description={intro}
        className="bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)]"
      >
        <div className="space-y-3">
          {stages.map((stage) => (
            <div
              key={stage.label}
              className="flex flex-col gap-3 rounded-[20px] border border-slate-200 p-4 md:flex-row md:items-start md:justify-between"
            >
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
                  {kind}
                </p>
                <p className="mt-1 text-base font-semibold text-ink">{stage.label}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{stage.detail}</p>
              </div>
              <StatusBadge status={stage.status} />
            </div>
          ))}
        </div>
      </Panel>

      <div className="space-y-5">
        <Panel
          title="工作台原则"
          description="这个前端把不同产品的流程拆开，而不是继续堆在一个总控面板里。"
        >
          <ul className="space-y-3 text-sm leading-6 text-slate-600">
            <li>输入区、运行态和结果区分开呈现。</li>
            <li>任务队列和项目管理统一收口，不在每个页面重复实现。</li>
            <li>预览、日志、质量面板抽成可复用组件。</li>
          </ul>
        </Panel>
        <Panel title={rightTitle} description={rightBody}>
          <div className="rounded-[20px] bg-shell p-4 text-sm leading-6 text-slate-600">
            API 对接刻意延后到独立 hooks 层，这样后端可以继续并行开发，不会被页面结构牵制。
          </div>
        </Panel>
      </div>
    </div>
  );
}
