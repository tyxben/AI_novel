"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Key,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Server,
  Cpu,
  Settings2,
  Image as ImageIcon,
  Film,
  Brain,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Panel } from "@/components/ui/panel";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const STORAGE_KEY = "ai-novel-settings";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

type KeyConfig = {
  name: string;
  envKey: string;
  label: string;
  placeholder: string;
  icon: typeof Key;
};

type TestResult = {
  status: "idle" | "testing" | "success" | "error";
  message?: string;
};

/* ------------------------------------------------------------------ */
/*  API Key definitions                                               */
/* ------------------------------------------------------------------ */

const API_KEYS: KeyConfig[] = [
  {
    name: "gemini",
    envKey: "GEMINI_API_KEY",
    label: "Gemini API Key",
    placeholder: "AIza...",
    icon: Brain,
  },
  {
    name: "deepseek",
    envKey: "DEEPSEEK_API_KEY",
    label: "DeepSeek API Key",
    placeholder: "sk-...",
    icon: Brain,
  },
  {
    name: "openai",
    envKey: "OPENAI_API_KEY",
    label: "OpenAI API Key",
    placeholder: "sk-...",
    icon: Brain,
  },
  {
    name: "siliconflow",
    envKey: "SILICONFLOW_API_KEY",
    label: "SiliconFlow API Key",
    placeholder: "sk-...",
    icon: ImageIcon,
  },
  {
    name: "dashscope",
    envKey: "DASHSCOPE_API_KEY",
    label: "阿里云 DashScope API Key",
    placeholder: "sk-...",
    icon: ImageIcon,
  },
];

/* ------------------------------------------------------------------ */
/*  Settings persistence (localStorage)                               */
/* ------------------------------------------------------------------ */

function loadSettings(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveSettings(settings: Record<string, string>) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

/* ------------------------------------------------------------------ */
/*  Component: API Key Row                                            */
/* ------------------------------------------------------------------ */

function ApiKeyRow({
  config,
  value,
  onChange,
  testResult,
  onTest,
}: {
  config: KeyConfig;
  value: string;
  onChange: (val: string) => void;
  testResult: TestResult;
  onTest: () => void;
}) {
  const Icon = config.icon;
  const [showKey, setShowKey] = useState(false);

  return (
    <div className="rounded-[20px] border border-slate-100 p-4 transition hover:border-slate-200">
      <div className="flex items-center gap-3">
        <Icon className="h-4 w-4 text-accent" />
        <div className="flex-1">
          <p className="text-sm font-medium text-ink">{config.label}</p>
          <p className="text-xs text-slate-400">{config.envKey}</p>
        </div>
        {testResult.status === "success" && (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        )}
        {testResult.status === "error" && (
          <XCircle className="h-4 w-4 text-rose-500" />
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <div className="relative flex-1">
          <input
            type={showKey ? "text" : "password"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={config.placeholder}
            className="w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2 pr-16 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <button
            type="button"
            onClick={() => setShowKey(!showKey)}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
          >
            {showKey ? "隐藏" : "显示"}
          </button>
        </div>
        <button
          type="button"
          onClick={onTest}
          disabled={!value.trim() || testResult.status === "testing"}
          className="inline-flex items-center gap-1.5 rounded-[12px] border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-shell disabled:opacity-50"
        >
          {testResult.status === "testing" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Key className="h-3 w-3" />
          )}
          测试连接
        </button>
      </div>

      {testResult.message && (
        <p
          className={`mt-2 text-xs ${
            testResult.status === "success"
              ? "text-emerald-600"
              : "text-rose-600"
          }`}
        >
          {testResult.message}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Settings Page                                                */
/* ------------------------------------------------------------------ */

export default function SettingsPage() {
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>(
    {}
  );

  // Default settings
  const [llmProvider, setLlmProvider] = useState("auto");
  const [imageBackend, setImageBackend] = useState("siliconflow");
  const [videoBackend, setVideoBackend] = useState("none");
  const [workers, setWorkers] = useState(1);

  // Health check
  const [healthStatus, setHealthStatus] = useState<
    "unknown" | "checking" | "ok" | "error"
  >("unknown");
  const [taskCount, setTaskCount] = useState<number | null>(null);

  // Load settings from localStorage
  useEffect(() => {
    const saved = loadSettings();
    const keyValues: Record<string, string> = {};
    API_KEYS.forEach((k) => {
      keyValues[k.name] = saved[k.envKey] ?? "";
    });
    setKeys(keyValues);

    if (saved._llmProvider) setLlmProvider(saved._llmProvider);
    if (saved._imageBackend) setImageBackend(saved._imageBackend);
    if (saved._videoBackend) setVideoBackend(saved._videoBackend);
    if (saved._workers) setWorkers(parseInt(saved._workers, 10) || 1);
  }, []);

  // Save keys whenever they change (debounced via effect)
  const persistSettings = useCallback(() => {
    const toSave: Record<string, string> = {
      _llmProvider: llmProvider,
      _imageBackend: imageBackend,
      _videoBackend: videoBackend,
      _workers: String(workers),
    };
    API_KEYS.forEach((k) => {
      if (keys[k.name]) toSave[k.envKey] = keys[k.name];
    });
    saveSettings(toSave);
  }, [keys, llmProvider, imageBackend, videoBackend, workers]);

  useEffect(() => {
    persistSettings();
  }, [persistSettings]);

  const handleKeyChange = (name: string, value: string) => {
    setKeys((prev) => ({ ...prev, [name]: value }));
  };

  const handleTestKey = async (name: string) => {
    const keyConfig = API_KEYS.find((k) => k.name === name);
    if (!keyConfig) return;

    setTestResults((prev) => ({
      ...prev,
      [name]: { status: "testing" },
    }));

    try {
      // Simple connectivity test: try to reach the health endpoint
      // In a real setup, POST /api/settings/test-key would validate the key
      // For now, we just check if the key looks valid
      const value = keys[name]?.trim();
      if (!value) {
        setTestResults((prev) => ({
          ...prev,
          [name]: { status: "error", message: "密钥为空" },
        }));
        return;
      }

      // Basic format validation
      if (keyConfig.name === "gemini" && !value.startsWith("AIza")) {
        setTestResults((prev) => ({
          ...prev,
          [name]: {
            status: "error",
            message: "Gemini 密钥通常以 AIza 开头",
          },
        }));
        return;
      }

      if (
        (keyConfig.name === "deepseek" || keyConfig.name === "openai") &&
        !value.startsWith("sk-")
      ) {
        setTestResults((prev) => ({
          ...prev,
          [name]: {
            status: "error",
            message: "密钥格式不正确，通常以 sk- 开头",
          },
        }));
        return;
      }

      // Mark as success if format looks OK
      setTestResults((prev) => ({
        ...prev,
        [name]: { status: "success", message: "密钥格式正确，已保存到本地" },
      }));
    } catch {
      setTestResults((prev) => ({
        ...prev,
        [name]: { status: "error", message: "测试失败" },
      }));
    }
  };

  const checkHealth = async () => {
    setHealthStatus("checking");
    try {
      const res = await fetch(`${API_BASE}/api/health`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        setHealthStatus("ok");
      } else {
        setHealthStatus("error");
      }
    } catch {
      setHealthStatus("error");
    }

    // Also fetch task count
    try {
      const res = await fetch(`${API_BASE}/api/tasks?limit=1000`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        const tasks = await res.json();
        setTaskCount(Array.isArray(tasks) ? tasks.length : 0);
      }
    } catch {
      setTaskCount(null);
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  return (
    <>
      <PageHeader
        eyebrow="设置"
        title="系统设置"
        description="管理 API 密钥、默认配置和后端服务状态。密钥保存在浏览器本地，通过请求头传递给后端。"
      />

      <div className="space-y-5 px-6 py-6 md:px-8">
        {/* API Keys Section */}
        <Panel title="服务商密钥" description="配置各服务商的 API Key，密钥仅保存在浏览器 localStorage 中">
          <div className="space-y-3">
            {API_KEYS.map((keyConfig) => (
              <ApiKeyRow
                key={keyConfig.name}
                config={keyConfig}
                value={keys[keyConfig.name] ?? ""}
                onChange={(val) => handleKeyChange(keyConfig.name, val)}
                testResult={testResults[keyConfig.name] ?? { status: "idle" }}
                onTest={() => handleTestKey(keyConfig.name)}
              />
            ))}
          </div>
        </Panel>

        {/* Defaults Section */}
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel title="默认配置" description="模型和生成服务的默认选择">
            <div className="space-y-5">
              {/* LLM Provider */}
              <div>
                <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink">
                  <Brain className="h-4 w-4 text-accent" />
                  LLM 服务商
                </label>
                <select
                  value={llmProvider}
                  onChange={(e) => setLlmProvider(e.target.value)}
                  className="w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="auto">自动检测 (推荐)</option>
                  <option value="gemini">Google Gemini</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="openai">OpenAI</option>
                  <option value="ollama">Ollama (本地)</option>
                </select>
                <p className="mt-1 text-xs text-slate-400">
                  自动检测优先级：Gemini &gt; DeepSeek &gt; OpenAI &gt; Ollama
                </p>
              </div>

              {/* Image Backend */}
              <div>
                <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink">
                  <ImageIcon className="h-4 w-4 text-accent" />
                  图片生成后端
                </label>
                <select
                  value={imageBackend}
                  onChange={(e) => setImageBackend(e.target.value)}
                  className="w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="siliconflow">SiliconFlow (免费)</option>
                  <option value="dashscope">阿里云万相</option>
                  <option value="together">Together.ai</option>
                  <option value="diffusers">本地 Diffusers</option>
                </select>
              </div>

              {/* Video Backend */}
              <div>
                <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink">
                  <Film className="h-4 w-4 text-accent" />
                  视频生成后端
                </label>
                <select
                  value={videoBackend}
                  onChange={(e) => setVideoBackend(e.target.value)}
                  className="w-full rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="none">不使用 (静态图模式)</option>
                  <option value="kling">可灵 (Kling)</option>
                  <option value="seedance">即梦 (Seedance)</option>
                  <option value="minimax">MiniMax 海螺</option>
                  <option value="sora">OpenAI Sora</option>
                </select>
              </div>

              {/* Workers */}
              <div>
                <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink">
                  <Users className="h-4 w-4 text-accent" />
                  任务队列 Worker 数量：{workers}
                </label>
                <input
                  type="range"
                  min={1}
                  max={4}
                  step={1}
                  value={workers}
                  onChange={(e) => setWorkers(parseInt(e.target.value, 10))}
                  className="w-full accent-accent"
                />
                <div className="mt-1 flex justify-between text-xs text-slate-400">
                  <span>1</span>
                  <span>4</span>
                </div>
              </div>
            </div>
          </Panel>

          {/* System Info Section */}
          <Panel title="系统信息" description="后端服务健康状态和任务队列">
            <div className="space-y-4">
              {/* Health Check */}
              <div className="rounded-[20px] border border-slate-100 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Server className="h-4 w-4 text-accent" />
                    <div>
                      <p className="text-sm font-medium text-ink">
                        后端服务状态
                      </p>
                      <p className="text-xs text-slate-400">
                        {API_BASE}/api/health
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {healthStatus === "ok" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                        <CheckCircle2 className="h-3 w-3" />
                        正常运行
                      </span>
                    )}
                    {healthStatus === "error" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700">
                        <XCircle className="h-3 w-3" />
                        无法连接
                      </span>
                    )}
                    {healthStatus === "checking" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-700">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        检测中
                      </span>
                    )}
                    {healthStatus === "unknown" && (
                      <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500">
                        未检测
                      </span>
                    )}
                    <button
                      onClick={checkHealth}
                      className="rounded-lg p-1.5 text-slate-400 transition hover:bg-shell hover:text-slate-600"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>

              {/* Task Queue Status */}
              <div className="rounded-[20px] border border-slate-100 p-4">
                <div className="flex items-center gap-3">
                  <Cpu className="h-4 w-4 text-accent" />
                  <div>
                    <p className="text-sm font-medium text-ink">
                      任务队列
                    </p>
                    <p className="text-xs text-slate-400">
                      {taskCount !== null
                        ? `共 ${taskCount} 个任务`
                        : "无法获取任务状态"}
                    </p>
                  </div>
                </div>
              </div>

              {/* Connection Info */}
              <div className="rounded-[20px] bg-shell p-4">
                <div className="flex items-center gap-2">
                  <Settings2 className="h-4 w-4 text-slate-400" />
                  <p className="text-xs font-medium text-slate-500">
                    连接信息
                  </p>
                </div>
                <div className="mt-2 space-y-1 text-xs text-slate-500">
                  <p>
                    API 地址：
                    <span className="font-mono text-ink">{API_BASE}</span>
                  </p>
                  <p>
                    环境变量：
                    <span className="font-mono text-slate-600">
                      NEXT_PUBLIC_API_BASE_URL
                    </span>
                  </p>
                </div>
              </div>

              {/* Startup hint */}
              {healthStatus === "error" && (
                <div className="rounded-[16px] bg-amber-50 p-3">
                  <p className="text-xs font-medium text-amber-700">
                    启动后端服务
                  </p>
                  <pre className="mt-1 font-mono text-xs text-amber-600">
                    python -m src.task_queue.server
                  </pre>
                </div>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
