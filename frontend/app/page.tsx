"use client";

import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { PhoneCall, TrendingUp, AlertTriangle, RefreshCw } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000") + "/api";

type Cluster = {
  id: string;
  label: string;
  description: string;
  volume: number;
  sentiment: string;
  frustration_index: number;
  intent_resolution_rate: number;
  urgency_score: number;
  created_at: string;
};

type InsightsData = {
  clusters: Cluster[];
  total_conversations: number;
  avg_frustration: number;
  avg_resolution_rate: number;
};

type Conversation = {
  id: string;
  vapi_call_id: string;
  summary: string;
  sentiment: string;
  success: boolean | null;
  duration_s: number | null;
  ended_reason: string;
  ingested_at: string;
  cluster_label: string;
};

const SENTIMENT_COLOR: Record<string, string> = {
  POSITIVE: "#22c55e",
  NEUTRAL: "#f59e0b",
  NEGATIVE: "#ef4444",
};

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-5 flex items-start gap-4 shadow-sm">
      <div className="p-2 rounded-lg bg-indigo-50 text-indigo-600">{icon}</div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-2xl font-bold text-gray-900">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const colors: Record<string, string> = {
    POSITIVE: "bg-green-100 text-green-700",
    NEUTRAL: "bg-yellow-100 text-yellow-700",
    NEGATIVE: "bg-red-100 text-red-700",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors[sentiment] ?? "bg-gray-100 text-gray-600"}`}>
      {sentiment}
    </span>
  );
}

export default function Dashboard() {
  const [insights, setInsights] = useState<InsightsData | null>(null);
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"clusters" | "conversations">("clusters");

  async function load() {
    setLoading(true);
    try {
      const [ins, cv] = await Promise.all([
        fetch(`${API}/insights`).then((r) => r.json()),
        fetch(`${API}/insights/conversations`).then((r) => r.json()),
      ]);
      setInsights(ins);
      setConvos(cv);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-8 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Agnost Signals</h1>
          <p className="text-xs text-gray-400">Voice Agent Analytics</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-800 font-medium"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            icon={<PhoneCall size={18} />}
            label="Total Conversations"
            value={insights?.total_conversations?.toString() ?? "—"}
          />
          <StatCard
            icon={<TrendingUp size={18} />}
            label="Clusters Detected"
            value={insights?.clusters?.length?.toString() ?? "—"}
            sub="unique intent groups"
          />
          <StatCard
            icon={<AlertTriangle size={18} />}
            label="Avg Frustration"
            value={insights ? `${(insights.avg_frustration * 100).toFixed(0)}%` : "—"}
            sub="across all clusters"
          />
        </div>

        {insights && insights.clusters.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Conversation Volume by Cluster</h2>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={insights.clusters} margin={{ left: -10 }}>
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="volume" radius={[4, 4, 0, 0]}>
                  {insights.clusters.map((c) => (
                    <Cell key={c.id} fill={SENTIMENT_COLOR[c.sentiment] ?? "#6366f1"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        <div>
          <div className="flex gap-1 border-b border-gray-200 mb-4">
            {(["clusters", "conversations"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
                  tab === t
                    ? "border-indigo-600 text-indigo-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "clusters" && (
            <div className="space-y-3">
              {loading && <p className="text-sm text-gray-400">Loading...</p>}
              {!loading && insights?.clusters.length === 0 && (
                <p className="text-sm text-gray-400">No clusters yet. Make a VAPI call to generate data.</p>
              )}
              {insights?.clusters.map((c) => (
                <div key={c.id} className="bg-white rounded-xl border border-gray-100 p-5 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-gray-900">{c.label}</h3>
                        <SentimentBadge sentiment={c.sentiment} />
                        {c.urgency_score > 2 && (
                          <span className="text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded-full font-medium">
                            High Urgency
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-500 mt-1">{c.description}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-2xl font-bold text-gray-900">{c.volume}</p>
                      <p className="text-xs text-gray-400">calls</p>
                    </div>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-4 text-center border-t pt-4">
                    <div>
                      <p className="text-xs text-gray-400">Frustration</p>
                      <p className="font-semibold text-gray-800">{(c.frustration_index * 100).toFixed(0)}%</p>
                      <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-red-400 rounded-full" style={{ width: `${Math.min(c.frustration_index * 100, 100)}%` }} />
                      </div>
                    </div>
                    <div>
                      <p className="text-xs text-gray-400">Urgency Score</p>
                      <p className="font-semibold text-gray-800">{c.urgency_score.toFixed(1)}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "conversations" && (
            <div className="space-y-3">
              {loading && <p className="text-sm text-gray-400">Loading...</p>}
              {!loading && convos.length === 0 && (
                <p className="text-sm text-gray-400">No conversations yet.</p>
              )}
              {convos.map((c) => (
                <div key={c.id} className="bg-white rounded-xl border border-gray-100 p-5 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-xs font-mono text-gray-400">{c.vapi_call_id.slice(0, 16)}…</span>
                        <SentimentBadge sentiment={c.sentiment} />
                        <span className="text-xs bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full">
                          {c.cluster_label}
                        </span>
                      </div>
                      <p className="text-sm text-gray-700">{c.summary}</p>
                    </div>
                    <div className="text-right shrink-0 text-xs text-gray-400">
                      {c.duration_s != null && <p>{c.duration_s}s</p>}
                      <p>{new Date(c.ingested_at).toLocaleTimeString()}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
